#!/usr/bin/env python3
"""Build headless metadata NX files from the original, read-only BeiDou IMG tree."""
import argparse
import hashlib
import json
import pathlib
import struct
import subprocess


def main():
    project = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=pathlib.Path, required=True,
                        help="External extracted BeiDou client directory containing Data/; read-only input")
    parser.add_argument("--output", type=pathlib.Path, default=project / "resources")
    parser.add_argument("--only", nargs="+", help="Category names; Base means root IMG files")
    parser.add_argument("--reuse-existing", action="store_true",
                        help="Resume this conversion using existing category outputs")
    args = parser.parse_args()
    client_root = args.client_root.resolve()
    source = client_root / "Data"
    output = args.output.resolve()
    if client_root == output or client_root in output.parents:
        parser.error("Output must be outside the original resource directory")
    if not source.is_dir():
        parser.error("Client Data directory does not exist")
    output.mkdir(parents=True, exist_ok=True)
    (project / "build").mkdir(exist_ok=True)
    (project / "evidence").mkdir(exist_ok=True)
    binary = project / "build/img_directory_to_nx"
    subprocess.run(["g++", "-std=c++17", "-O2", str(project / "tools/img_directory_to_nx.cpp"),
                    str(project.parent / "third_party/nolifewztonx/Keys.cpp"), "-o", str(binary)], check=True)
    converter_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    previous_path = output / "manifest.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
    categories = args.only or ["Base"] + sorted(p.name for p in source.iterdir() if p.is_dir())
    records = []
    for category in categories:
        category_source = source if category == "Base" else source / category
        if not category_source.is_dir() or pathlib.Path(category).name != category:
            parser.error("Invalid category: " + category)
        inputs = sorted(category_source.glob("*.img") if category == "Base"
                        else category_source.rglob("*.img"))
        digest = hashlib.sha256()
        for path in inputs:
            digest.update(str(path.relative_to(source)).encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        destination = output / (category + ".nx")
        if destination.exists():
            if not args.reuse_existing or previous is None:
                parser.error("Output exists; use a fresh output directory: " + str(destination))
            prior = next(record for record in previous["categories"] if record["category"] == category)
            if (previous["converter_sha256"] != converter_hash or
                    prior["input_tree_sha256"] != digest.hexdigest() or
                    prior["sha256"] != hashlib.sha256(destination.read_bytes()).hexdigest()):
                parser.error("Existing category does not match inputs/converter: " + category)
        else:
            temporary = output / (category + ".nx.tmp")
            command = [str(binary), str(category_source), str(temporary)]
            if category == "Base":
                command.append("--base")
            log_path = project / "evidence" / ("resource-" + category + ".log")
            with log_path.open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            temporary.replace(destination)
        raw = destination.read_bytes()
        magic, nodes, node_offset, strings, string_offset, bitmaps, bitmap_offset, audios, audio_offset = \
            struct.unpack_from("<IIQIQIQIQ", raw)
        if magic != 0x34474B50:
            raise ValueError("Invalid NX header: " + str(destination))
        record = {"category": category, "input_img_count": len(inputs),
                  "input_tree_sha256": digest.hexdigest(), "nodes": nodes, "strings": strings,
                  "bitmaps": bitmaps, "audio_entries": audios, "bytes": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest()}
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    manifest = {"format": "BeiDou headless metadata NX v1", "input_root": str(source),
                "metadata_only": True, "renderable_pixels": False, "playable_audio": False,
                "preserved": ["all property nodes", "canvas types and dimensions", "frame delay",
                              "origin", "bounds", "UOL links"],
                "converter_sha256": converter_hash,
                "categories": records}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
