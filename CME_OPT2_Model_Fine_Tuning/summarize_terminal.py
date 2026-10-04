"""Retain actual command output while omitting repetitive batch progress bars."""
import re
from pathlib import Path

TASK = Path(__file__).resolve().parent
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def main():
    output = ["CME-OPT2 actual terminal excerpts. Full logs persist on Modal industirx-cme-opt2:/reports.",
              "Batch progress bars omitted; epoch/loss/LR records and final class metrics retained.", ""]
    for name in ("smoke", "train", "resume", "followup", "targeted", "evaluate"):
        path = TASK / "reports" / f"{name}_terminal.txt"
        if not path.exists(): continue
        output += [f"=== {name}: {path.name} ==="]
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = ANSI.sub("", raw).strip()
            if not line or "━" in line or "──" in line: continue
            if (any(term in line for term in ("DATASET ", "Ultralytics 8.", "CME-OPT2", "AMP:", "optimizer:",
                                              "epochs completed", "EarlyStopping", "Resuming training", "Transferred ",
                                              "Optimizer stripped", "Model summary", "Traceback", "Error", "RuntimeError"))
                    or re.match(r"^(all|baekra|color issues|contamination|cut|gray stitch|selvet|stain|chemical hazard|fire|no helmet|smoke|water leak)\s+\d", line)):
                output.append(line)
        output.append("")
    (TASK / "reports/terminal_output.txt").write_text("\n".join(output)+"\n",encoding="utf-8")
    print("Measured terminal evidence summarized without changing values.")


if __name__ == "__main__":
    main()
