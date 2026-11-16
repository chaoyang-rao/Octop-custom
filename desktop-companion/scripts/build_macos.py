"""Build a native, ad-hoc signed Mac companion without changing Octop data."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.0"


def run(*args: str, **kwargs: object) -> None:
    subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=["arm64", "x86_64", "universal"], default="universal")
    parser.add_argument("--no-dmg", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--engine-dir", type=Path, default=ROOT / "build/engine")
    parser.add_argument("--pet-dir", type=Path, default=ROOT / "assets/internal/dora3d/frames")
    args = parser.parse_args()
    if not args.pet_dir.is_dir() or not (args.pet_dir / "pet.json").is_file():
        parser.error("Provide the approved internal character pack with --pet-dir; artwork is not downloaded or published automatically")
    pet_manifest=json.loads((args.pet_dir/"pet.json").read_text())
    for animation in pet_manifest["animations"].values():
        for name in animation["frames"]:
            if Path(name).name!=name or not name.endswith('.png') or not (args.pet_dir/name).is_file():
                parser.error("Invalid internal sprite frame path")
    if not args.skip_web:
        if not (ROOT / "node_modules").is_dir():
            run("npm", "ci", "--no-audit", "--no-fund")
        run("npm", "run", "build")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
    ).strip()
    sources = [str(path) for path in sorted((ROOT / "macos").glob("*.swift"))]
    architectures = ["arm64", "x86_64"] if args.arch == "universal" else [args.arch]
    binaries = []
    for arch in architectures:
        binary = build / f"OctopCompanion-{arch}"
        run(
            "xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-parse-as-library",
            "-O",
            "-sdk",
            sdk,
            "-target",
            f"{arch}-apple-macosx13.0",
            "-module-cache-path",
            str(build / "ModuleCache"),
            "-framework",
            "AppKit",
            "-framework",
            "WebKit",
            "-framework",
            "AVFoundation",
            "-framework",
            "Speech",
            "-framework",
            "Carbon",
            *sources,
            "-o",
            str(binary),
        )
        binaries.append(binary)
    app = ROOT / "dist/哆啦.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    executable = contents / "MacOS/OctopCompanion"
    executable.parent.mkdir(parents=True)
    if len(binaries) == 2:
        run("lipo", "-create", *map(str, binaries), "-output", str(executable))
    else:
        shutil.copy2(binaries[0], executable)
    executable.chmod(0o755)
    resources = contents / "Resources"
    shutil.copytree(ROOT / "dist/web", resources / "web")
    engine_manifest = json.loads((args.engine_dir / "manifest.json").read_text())
    if not set(architectures).issubset(engine_manifest["architectures"]):
        parser.error("Prepare the matching engine archives with scripts/prepare_engine.py first")
    shutil.copytree(args.engine_dir, resources / "Engine")
    shutil.copy2(ROOT / "scripts/engine_entry.py", resources / "engine_entry.py")
    shutil.copytree(args.pet_dir, resources / "Pet")
    shutil.copy2(
        args.pet_dir / "ASSET-NOTICE.txt", resources / "ASSET-NOTICE.txt"
    )
    info = {
        "CFBundleName": "哆啦",
        "CFBundleDisplayName": "哆啦",
        "CFBundleIdentifier": "com.chaoyangrao.octop.companion",
        "CFBundleExecutable": "OctopCompanion",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": "2026111701",
        "CFBundleURLTypes": [{"CFBundleURLName": "Dora desktop companion", "CFBundleURLSchemes": ["octop-companion"], "CFBundleTypeRole": "Viewer"}],
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "在你点击语音输入时，将语音转为问题。",
        "NSSpeechRecognitionUsageDescription": "将你主动录入的语音识别为文字，便于向哆啦提问。",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True, "NSAllowsArbitraryLoads": True},
        "NSHighResolutionCapable": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    run("codesign", "--force", "--deep", "--sign", "-", str(app))
    run("codesign", "--verify", "--deep", "--strict", str(app))
    run(str(executable), "--self-test")
    artifacts = []
    if not args.no_dmg:
        stage = build / "dmg-stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir()
        shutil.copytree(app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        dmg = ROOT / "dist" / f"Dora-macos-{args.arch}-{VERSION}-internal.dmg"
        run(
            "hdiutil",
            "create",
            "-volname",
            "哆啦预览",
            "-srcfolder",
            str(stage),
            "-format",
            "UDZO",
            "-ov",
            str(dmg),
        )
        run("hdiutil", "verify", str(dmg))
        artifacts.append(
            {
                "file": dmg.name,
                "bytes": dmg.stat().st_size,
                "sha256": hashlib.sha256(dmg.read_bytes()).hexdigest(),
            }
        )
    report = {
        "version": VERSION,
        "architectures": architectures,
        "app": str(app),
        "signing": "ad-hoc; not notarized",
        "backend_included": True,
        "external_octop_required": False,
        "engine_data_directory": "~/Library/Application Support/OctopCompanion/Data",
        "character": pet_manifest["name"],
        "artwork_distribution_terms": "internal small-team use; generated artwork; character rights remain separate",
        "artifacts": artifacts,
    }
    (ROOT / "dist/build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
