from __future__ import annotations

from pathlib import Path

from . import build_md, parse_xml


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    input_dir = repo_root / "downloads"
    output_dir = repo_root / "outputs"

    xml_files = list(input_dir.glob("*.xml"))
    if not xml_files:
        print("downloads/ 中没有找到 XML 文件")
        return 0

    output_dir.mkdir(exist_ok=True)

    print(f"找到 {len(xml_files)} 个 XML 文件，开始转换..")
    ok, fail = 0, 0
    for xml_file in xml_files:
        out_path = output_dir / (xml_file.stem + ".md")
        try:
            info = parse_xml(xml_file)
            md_text = build_md(info)
            out_path.write_text(md_text, encoding="utf-8")
            print(f"  [OK] {xml_file.name} -> {out_path.name}")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {xml_file.name}: {e}")
            fail += 1

    print(f"\n完成：{ok} 成功，{fail} 失败")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

