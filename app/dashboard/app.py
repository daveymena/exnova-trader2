"""Minimal dashboard for monitoring bot status.

Runs as a simple CLI or can be extended with web UI.
"""


class Dashboard:
    def __init__(self):
        self.status_lines = []

    def update(self, data: dict):
        self.status_lines.clear()
        mode = data.get("mode", "unknown").upper()
        self.status_lines.append(f"Mode: {mode}")
        self.status_lines.append(f"Equity: ${data.get('equity', 0):.2f}")
        self.status_lines.append(f"Balance: ${data.get('balance', 0):.2f}")
        self.status_lines.append(f"Daily P&L: ${data.get('daily_pnl', 0):.2f}")
        self.status_lines.append(f"Daily Drawdown: {data.get('daily_drawdown', 0):.2f}%")
        self.status_lines.append(f"Open Positions: {data.get('open_positions', 0)}")
        self.status_lines.append(f"Regime: {data.get('regime', 'N/A')}")
        self.status_lines.append(f"MTF Alignment: {data.get('mtf_alignment', 'N/A')}")
        self.status_lines.append(f"Last Signal: {data.get('last_signal', 'N/A')}")
        self.status_lines.append(f"Risk Status: {data.get('risk_status', 'NORMAL')}")

    def display(self):
        print("\n" + "=" * 50)
        for line in self.status_lines:
            print(f"  {line}")
        print("=" * 50)
