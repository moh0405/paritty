"""Download public source data into data/raw (spec §6). Sources are cited in DATA.md."""
import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
SDTM_URL = ("https://github.com/cdisc-org/sdtm-adam-pilot-project/raw/master/updated-pilot-submission-package/"
            "900172/m5/datasets/cdiscpilot01/tabulations/sdtm/{dom}.xpt")
DOMAINS = ["dm", "ae", "lb", "vs", "ex", "ds", "sv", "cm", "tv", "ta", "suppae", "mh"]
REQUIRED = {"dm", "ae", "lb", "vs"}
CTGOV_SEARCH = ("https://clinicaltrials.gov/api/v2/studies?query.cond=Alzheimer&filter.overallStatus=COMPLETED"
                "&query.term=AREA[StudyType]INTERVENTIONAL&pageSize=1")


def get(url: str) -> requests.Response:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    failed_required = []
    for dom in DOMAINS:
        url = SDTM_URL.format(dom=dom)
        try:
            df = pd.read_sas(BytesIO(get(url).content), format="xport", encoding="latin-1")
            df.to_parquet(RAW / f"{dom}.parquet")
            print(f"{dom}: {len(df)} rows, {len(df.columns)} cols")
        except Exception as exc:
            print(f"{dom}: SKIPPED ({exc}). Expected at {RAW / (dom + '.parquet')} from {url}")
            if dom in REQUIRED:
                failed_required.append(dom)
    try:
        study = get(CTGOV_SEARCH).json()["studies"][0]
        (RAW / "ctgov_study.json").write_text(json.dumps(study, indent=2))
        print("ctgov:", study["protocolSection"]["identificationModule"]["nctId"])
    except Exception as exc:
        print(f"ctgov: SKIPPED ({exc})")
    try:
        (RAW / "openfda_sample.json").write_text(get("https://api.fda.gov/drug/event.json?limit=5").text)
        print("openfda: ok")
    except Exception as exc:
        print(f"openfda: SKIPPED ({exc})")
    if failed_required:
        raise SystemExit(f"required domains missing: {failed_required}")


if __name__ == "__main__":
    main()
