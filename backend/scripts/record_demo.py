"""Advance the sim from the seeded state with the configured LLM mode (use LLM_MODE=record to fill fixtures/llm_cache).
`make record-llm` runs this for the 60-day demo (spec §15)."""
import sys
import time

from app.seed.common import connect
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset


def main(days: int) -> None:
    with connect() as conn:
        reset(conn)
        conn.commit()
        cycle = DailyCycle(conn)
        t = time.time()
        for _ in range(days):
            rep = cycle.run()
            conn.commit()
            print(rep.day, {k: v for k, v in rep.as_dict().items() if k not in ("day", "released") and v}, f"{time.time() - t:.0f}s", flush=True)
        for row in conn.execute("SELECT f.module, f.verification_status, count(*) FROM ai.findings f GROUP BY 1, 2 ORDER BY 1, 2"):
            print(row)
        print(conn.execute("SELECT job, cache_hit, count(*), sum(input_tokens), sum(output_tokens), round(avg(latency_ms)) FROM ai.llm_calls GROUP BY 1, 2").fetchall())


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
