#!/usr/bin/env python3
"""Script standalone per testare l'API IRSAP senza Home Assistant.

Funzionalità:
 - Login via Cognito (SRP) usando le stesse costanti dell'integrazione.
 - Recupero envID (se non fornito) con la query ListEnvironments.
 - Recupero payload shadow con la query GetShadow.
 - Parsing dei dispositivi e dei valori sensore riusando la funzione extract_device_info.
 - Output in JSON (compatto o pretty) o raw payload opzionale.

Prerequisiti:
  pip install aiohttp warrant

Variabili d'ambiente accettate:
  IRSAP_USERNAME (obbligatorio)  
  IRSAP_PASSWORD (obbligatorio)  
  IRSAP_ENV_ID  (opzionale; se assente viene richiesto via API)

Esempi:
  python test_irsap_api.py --pretty
  IRSAP_ENV_ID=abc123 python test_irsap_api.py -o dispositivi.json
  python test_irsap_api.py --raw --filter SERIAL1
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import asyncio
import logging
from typing import Any, Dict, List, Optional

# Costanti IRSAP (copiata dall'integrazione)
USER_POOL_ID = "eu-west-1_qU4ok6EGG"
CLIENT_ID = "4eg8veup8n831ebokk4ii5uasf"
REGION = "eu-west-1"


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    tmp_suffix="_TMP",
    enb_suffix="_ENB",
    exclude_suffix="E_NAM",
):
    """Estrae informazioni dispositivi dal payload shadow IRSAP (copiata dall'integrazione)."""
    devices_info = []

    # Suffixi di interesse per le chiavi
    suffixes = [
        "_CNT",
        "_FWV",
        "_TYP",
        "_SLV",
        "_LUP",
        "_X_ipAddress",
        "_X_filPiloteEnabled",
        "_X_filPiloteStatus",
        "_X_standby",
        "_X_OpenWindowSensorEnabled",
        "_X_OpenWindowDetected",
        "_X_OpenWindowSensorOffTime",
        "_X_temperatureSensorOffset",
        "_X_hysteresis",
        "_X_vocValue",
        "_X_co2Value",
        "_X_lock",
        "_AIQ",
    ]

    # Liste per raccogliere le chiavi
    nam_keys = []
    cnt_keys = []
    fwv_keys = []
    typ_keys = []
    slv_keys = []
    lup_keys = []
    ip_keys = []
    pilote_enb_keys = []
    pilote_sta_keys = []
    stand_keys = []
    openwin_enab_keys = []
    openwin_dect_keys = []
    openwin_off_keys = []
    temp_off_keys = []
    hyst_keys = []
    voc_keys = []
    co2_keys = []
    lock_keys = []
    aiq_keys = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Raccogli chiavi _NAM e aggiungi i dettagli iniziali
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    device_info = {
                        "serial": value,
                        "temperature": 0,  # Default a 0 se non trovata
                        "state": "OFF",  # Default a OFF se non trovato
                    }
                    nam_keys.append((key, device_info))

                # Controlla se la chiave finisce con uno dei suffissi
                if any(key.endswith(suffix) for suffix in suffixes):
                    # Aggiungi la chiave alla lista corrispondente
                    if key.endswith("_CNT"):
                        cnt_keys.append((key, value))
                    elif key.endswith("_FWV"):
                        fwv_keys.append((key, value))
                    elif key.endswith("_TYP"):
                        typ_keys.append((key, value))
                    elif key.endswith("_SLV"):
                        slv_keys.append((key, value))
                    elif key.endswith("_LUP"):
                        lup_keys.append((key, value))
                    elif key.endswith("_X_ipAddress"):
                        ip_keys.append((key, value))
                    elif key.endswith("_X_filPiloteEnabled"):
                        pilote_enb_keys.append((key, value))
                    elif key.endswith("_X_filPiloteStatus"):
                        pilote_sta_keys.append((key, value))
                    elif key.endswith("_X_standby"):
                        stand_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowSensorEnabled"):
                        openwin_enab_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowDetected"):
                        openwin_dect_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowSensorOffTime"):
                        openwin_off_keys.append((key, value))
                    elif key.endswith("_X_temperatureSensorOffset"):
                        temp_off_keys.append((key, value))
                    elif key.endswith("_X_hysteresis"):
                        hyst_keys.append((key, value))
                    elif key.endswith("_X_vocValue"):
                        voc_keys.append((key, value))
                    elif key.endswith("_X_co2Value"):
                        co2_keys.append((key, value))
                    elif key.endswith("_X_lock"):
                        lock_keys.append((key, value))
                    elif key.endswith("_AIQ"):
                        aiq_keys.append((key, value))

                # Ricorsione per esplorare eventuali chiavi annidate
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca nel payload
    find_device_keys(payload)

    # Associa ogni _NAM ai suoi corrispondenti attributi
    for i, (nam_key, device_info) in enumerate(nam_keys):
        base_key = nam_key[: -len(nam_suffix)]
        corresponding_tmp_key = base_key + tmp_suffix
        corresponding_enb_key = base_key + enb_suffix

        # Trova la temperatura
        if corresponding_tmp_key in payload:
            tmp_value = payload.get(corresponding_tmp_key)
            device_info["temperature"] = (
                float(tmp_value) / 10 if tmp_value is not None else 0
            )

        # Trova lo stato (ON/OFF)
        if corresponding_enb_key in payload:
            enb_value = payload.get(corresponding_enb_key)
            device_info["state"] = "HEAT" if enb_value == 1 else "OFF"

        # Associa altri dati (es. MAC, firmware, IP, etc.)
        if i < len(cnt_keys):
            device_info["mac"] = cnt_keys[i][1]
        if i < len(fwv_keys):
            device_info["firmware"] = fwv_keys[i][1]
        if i < len(typ_keys):
            device_info["model"] = typ_keys[i][1]
        if i < len(slv_keys):
            device_info["wifi_signal"] = slv_keys[i][1]
        if i < len(lup_keys):
            device_info["last_update"] = lup_keys[i][1]
        if i < len(ip_keys):
            device_info["ip_address"] = ip_keys[i][1]
        if i < len(pilote_enb_keys):
            device_info["pilote_enable"] = pilote_enb_keys[i][1]
        if i < len(pilote_sta_keys):
            device_info["pilote_status"] = pilote_sta_keys[i][1]
        if i < len(stand_keys):
            device_info["standby"] = stand_keys[i][1]
        if i < len(openwin_enab_keys):
            device_info["open_window_enabled"] = openwin_enab_keys[i][1]
        if i < len(openwin_dect_keys):
            device_info["openwindow_detected"] = openwin_dect_keys[i][1]
        if i < len(openwin_off_keys):
            device_info["openwindow_offset"] = openwin_off_keys[i][1]
        if i < len(temp_off_keys):
            device_info["temperature_offset"] = temp_off_keys[i][1]
        if i < len(hyst_keys):
            device_info["hysteresis"] = hyst_keys[i][1]
        if i < len(voc_keys):
            device_info["voc"] = voc_keys[i][1]
        if i < len(co2_keys):
            device_info["co2"] = co2_keys[i][1]
        if i < len(lock_keys):
            device_info["lock"] = lock_keys[i][1]
        if i < len(aiq_keys):
            device_info["aiq"] = aiq_keys[i][1]

        devices_info.append(device_info)

    return devices_info

try:
    from warrant import Cognito  # type: ignore
except ImportError:  # pragma: no cover
    print("Manca il pacchetto 'warrant'. Installa con: pip install warrant")
    sys.exit(1)

try:
    import aiohttp  # type: ignore
except ImportError:  # pragma: no cover
    print("Manca il pacchetto 'aiohttp'. Installa con: pip install aiohttp")
    sys.exit(1)

LOG = logging.getLogger("irsap_test")


GRAPHQL_ENDPOINT = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"


def login_with_srp(username: str, password: str) -> str:
    """Esegue login SRP Cognito e restituisce l'access token."""
    u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
    u.authenticate(password=password)
    return u.access_token  # type: ignore[attr-defined]


async def fetch_env_id(session: aiohttp.ClientSession, token: str) -> str:
    """Recupera il primo envId disponibile."""
    query = {
        "operationName": "ListEnvironments",
        "variables": {},
        "query": (
            "query ListEnvironments {\n listEnvironments {\n environments {\n envId\n envName\n userRole\n __typename\n }\n __typename\n }\n}\n"
        ),
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with session.post(GRAPHQL_ENDPOINT, json=query, headers=headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"ListEnvironments fallita: {resp.status} - {text}")
        data = await resp.json()
        envs = (
            data.get("data", {})
            .get("listEnvironments", {})
            .get("environments", [])
        )
        if not envs:
            raise RuntimeError("Nessun environment trovato")
        return envs[0]["envId"]


async def fetch_shadow_payload(session: aiohttp.ClientSession, token: str, env_id: str) -> Dict[str, Any]:
    """Recupera il payload shadow grezzo (dict deserializzato)."""
    query = {
        "operationName": "GetShadow",
        "variables": {"envId": env_id},
        "query": (
            "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n"
        ),
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with session.post(GRAPHQL_ENDPOINT, json=query, headers=headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"GetShadow fallita: {resp.status} - {text}")
        data = await resp.json()
        shadow_raw = data["data"]["getShadow"]["payload"]
        parsed_shadow = json.loads(shadow_raw)
        
        # Log del payload completo per analisi
        LOG.info("=== PAYLOAD COMPLETO API RESPONSE ===")
        LOG.info("Raw GraphQL response: %s", json.dumps(data, indent=2))
        LOG.info("=== SHADOW PAYLOAD PARSED ===")
        LOG.info("Parsed shadow: %s", json.dumps(parsed_shadow, indent=2))
        LOG.info("=== END PAYLOAD LOGGING ===")
        
        return parsed_shadow


def filter_devices(devices: List[Dict[str, Any]], pattern: Optional[str]) -> List[Dict[str, Any]]:
    if not pattern:
        return devices
    pattern_upper = pattern.upper()
    return [d for d in devices if pattern_upper in str(d.get("serial", "")).upper()]


def load_dotenv_if_present(filename: str = ".env") -> None:
    """Carica un file .env semplice (chiave=valore, ignora righe vuote e commenti)."""
    if not os.path.isfile(filename):
        return
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                # Non sovrascrivere se già in env
                if k not in os.environ:
                    os.environ[k] = v
    except Exception as e:  # pragma: no cover
        LOG.warning("Errore nel parsing di %s: %s", filename, e)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Test API IRSAP e stampa valori sensori")
    p.add_argument("--username", help="Username (override variabile d'ambiente)")
    p.add_argument("--password", help="Password (override variabile d'ambiente)")
    p.add_argument("--env-id", help="Env ID (override variabile d'ambiente)")
    p.add_argument("--pretty", action="store_true", help="Output JSON formattato")
    p.add_argument("--raw", action="store_true", help="Stampa anche il payload raw")
    p.add_argument("--filter", help="Filtra per serial (substring case-insensitive)")
    p.add_argument(
        "-o", "--output", help="Salva l'output elaborato in un file JSON"
    )
    p.add_argument(
        "-v", "--verbose", action="count", default=0, help="Aumenta verbosità log"
    )
    return p


async def run(args: argparse.Namespace) -> int:
    username = args.username or os.getenv("IRSAP_USERNAME")
    password = args.password or os.getenv("IRSAP_PASSWORD")
    env_id = args.env_id or os.getenv("IRSAP_ENV_ID")

    if not username or not password:
        print("Errore: Specificare credenziali via --username/--password o variabili d'ambiente IRSAP_USERNAME / IRSAP_PASSWORD")
        return 2

    # Login (sincrono) eseguito in thread con asyncio.to_thread
    try:
        token = await asyncio.to_thread(login_with_srp, username, password)
    except Exception as e:
        LOG.error("Login fallito: %s", e)
        return 3

    async with aiohttp.ClientSession() as session:
        if not env_id:
            try:
                env_id = await fetch_env_id(session, token)
                LOG.info("Recuperato envID: %s", env_id)
            except Exception as e:
                LOG.error("Recupero envID fallito: %s", e)
                return 4

        try:
            shadow = await fetch_shadow_payload(session, token, env_id)
        except Exception as e:
            LOG.error("Recupero shadow fallito: %s", e)
            return 5

    desired = shadow.get("state", {}).get("desired", {})
    devices = extract_device_info(desired)
    devices = filter_devices(devices, args.filter)

    output_obj = {
        "envId": env_id,
        "deviceCount": len(devices),
        "devices": devices,
    }

    if args.raw:
        output_obj["rawShadow"] = shadow  # Attenzione: può essere grande

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_obj, f, ensure_ascii=False, indent=2)
        print(f"Output salvato in {args.output}")

    # Stampa su stdout
    if args.pretty:
        print(json.dumps(output_obj, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output_obj, ensure_ascii=False, separators=(",", ":")))

    return 0


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    # Carica .env prima di leggere le variabili
    load_dotenv_if_present()
    configure_logging(args.verbose)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:  # pragma: no cover
        print("Interrotto dall'utente", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
