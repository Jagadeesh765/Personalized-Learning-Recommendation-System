"""Generate twice with the same seed and compare CSV row counts and SHA-256 checksums."""
import argparse
import json
import tempfile
from pathlib import Path

from generate_data import BASE, generate


def compare_regenerations(scale="starter"):
    with tempfile.TemporaryDirectory(prefix="learning-repro-a-") as first_dir, \
         tempfile.TemporaryDirectory(prefix="learning-repro-b-") as second_dir:
        generate(scale, output_dir=first_dir)
        generate(scale, output_dir=second_dir)

        first = json.loads((Path(first_dir) / "outputs" / "source_manifest.json").read_text(encoding="utf-8"))
        second = json.loads((Path(second_dir) / "outputs" / "source_manifest.json").read_text(encoding="utf-8"))

        first_files = first["files"]
        second_files = second["files"]
        same_names = sorted(first_files) == sorted(second_files)
        differences = []
        if same_names:
            for name in sorted(first_files):
                if first_files[name]["rows"] != second_files[name]["rows"]:
                    differences.append({"file": name, "field": "rows"})
                if first_files[name]["sha256"] != second_files[name]["sha256"]:
                    differences.append({"file": name, "field": "sha256"})

        report = {
            "status": "PASS" if same_names and not differences else "FAIL",
            "scale": scale,
            "seed": first["seed"],
            "run_1_row_counts": first["row_counts"],
            "run_2_row_counts": second["row_counts"],
            "files_compared": len(first_files),
            "differences": differences,
            "method": "Two isolated generations; compare each CSV row count and SHA-256 checksum."
        }
        out = BASE / "outputs"
        out.mkdir(exist_ok=True)
        (out / "reproducibility_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", choices=["starter", "full"], default="starter")
    args = parser.parse_args()
    result = compare_regenerations(args.scale)
    raise SystemExit(0 if result["status"] == "PASS" else 1)
