from datetime import date, timedelta

from psycopg import Connection


class TrialClock:
    def __init__(self, conn: Connection):
        self.conn = conn

    def today(self) -> date:
        return self.conn.execute("SELECT today FROM ops.sim_clock WHERE id = 1").fetchone()[0]

    def study_start(self) -> date:
        return self.conn.execute("SELECT study_start FROM ops.sim_clock WHERE id = 1").fetchone()[0]

    def advance_one(self) -> date:
        day = self.today() + timedelta(days=1)
        self.conn.execute("UPDATE ops.sim_clock SET today = %s WHERE id = 1", (day,))
        return day

    def study_day(self) -> int:
        return (self.today() - self.study_start()).days
