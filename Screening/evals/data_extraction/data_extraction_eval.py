#!/usr/bin/env python3
"""
Data Extraction Evaluation Script
==================================
模仿前端调用 EnhancedDataExtraction.py 的逻辑，
从 datasets/ 读取 PDF，使用 Template_PICO6.xlsx 作为模板，
将提取结果输出到 outputs/ 目录，供人工比对 PICO6.xlsx 参考答案。

用法:
    cd Screening/evals/data_extraction
    python data_extraction_eval.py

    # 自定义 PICO 条件（JSON 字符串）
    python data_extraction_eval.py --pico-json '{"s":"RCT","p":"children","i":"iron","c":"placebo","o":"hemoglobin"}'

    # 指定项目类型
    python data_extraction_eval.py --project-type PICO
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 本脚本所在目录
EVAL_DIR = Path(__file__).resolve().parent
# Screening 目录
SCREENING_DIR = EVAL_DIR.parent.parent

# 默认路径
DATASETS_DIR = EVAL_DIR / "datasets/pdf"
TEMPLATE_PATH = EVAL_DIR / "datasets/Template_PICO6.xlsx"
PICO_JSON_PATH = EVAL_DIR / "datasets/PICO6.json"
OUTPUTS_DIR = EVAL_DIR / "outputs"
EXTRACTION_SCRIPT = SCREENING_DIR / "EnhancedDataExtraction.py"


def load_pico_from_json(path: Path) -> dict:
    """从 PICO6.json 读取 SPICO 条件，转换为前端传给后端的格式"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # O 字段可能是嵌套对象，需要展平成字符串
    outcome = data.get("O", "")
    if isinstance(outcome, dict):
        parts = []
        for category, items in outcome.items():
            if isinstance(items, list):
                parts.append(f"{category}: {', '.join(items)}")
            else:
                parts.append(f"{category}: {items}")
        outcome = "; ".join(parts)

    return {
        "s": data.get("S", ""),
        "p": data.get("P", ""),
        "i": data.get("I", ""),
        "c": data.get("C", ""),
        "o": outcome,
        "es": "",
    }


def build_command(
    python_exe: str,
    resources_dir: Path,
    template: Path,
    output_csv: Path,
    output_xlsx: Path,
    project_type: str,
    pico_json_str: str,
) -> list:
    """构建与前端 app.py 一致的 subprocess 命令行参数"""
    return [
        python_exe,
        str(EXTRACTION_SCRIPT),
        "--template", str(template),
        "--resources-dir", str(resources_dir),
        "--output-csv", str(output_csv),
        "--output-xlsx", str(output_xlsx),
        "--project-type", project_type,
        "--pico-json", pico_json_str,
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Data Extraction Evaluation - 模仿前端调用逻辑测试提取准确率"
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=DATASETS_DIR,
        help="PDF 数据集目录",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help="Excel 模板文件路径",
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=OUTPUTS_DIR,
        help="输出目录",
    )
    parser.add_argument(
        "--project-type",
        type=str,
        default="PICOS",
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="项目类型",
    )
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help="PICO 条件 JSON 字符串，留空则使用默认值",
    )
    args = parser.parse_args()

    # 校验路径
    if not args.datasets_dir.exists():
        print(f"错误: 数据集目录不存在: {args.datasets_dir}")
        sys.exit(1)
    if not args.template.exists():
        print(f"错误: 模板文件不存在: {args.template}")
        sys.exit(1)
    if not EXTRACTION_SCRIPT.exists():
        print(f"错误: 提取脚本不存在: {EXTRACTION_SCRIPT}")
        sys.exit(1)

    # 统计 PDF 数量
    pdf_files = list(args.datasets_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"错误: 数据集目录中没有 PDF 文件: {args.datasets_dir}")
        sys.exit(1)

    # 准备 PICO JSON：优先命令行参数，否则从 PICO6.json 读取
    if args.pico_json:
        pico_json_str = args.pico_json
    else:
        if not PICO_JSON_PATH.exists():
            print(f"错误: PICO 配置文件不存在: {PICO_JSON_PATH}")
            sys.exit(1)
        pico_dict = load_pico_from_json(PICO_JSON_PATH)
        pico_json_str = json.dumps(pico_dict, ensure_ascii=False)

    # 准备输出路径（带时间戳避免覆盖）
    args.outputs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = args.outputs_dir / f"eval_{timestamp}.csv"
    output_xlsx = args.outputs_dir / f"eval_{timestamp}.xlsx"

    # 构建命令（与 app.py run_data_extraction 一致）
    python_exe = sys.executable
    cmd = build_command(
        python_exe=python_exe,
        resources_dir=args.datasets_dir,
        template=args.template,
        output_csv=output_csv,
        output_xlsx=output_xlsx,
        project_type=args.project_type,
        pico_json_str=pico_json_str,
    )

    print("=" * 60)
    print("Data Extraction Evaluation")
    print("=" * 60)
    print(f"PDF 数量:    {len(pdf_files)}")
    print(f"项目类型:    {args.project_type}")
    print(f"PICO 条件:   {pico_json_str}")
    print(f"模板文件:    {args.template}")
    print(f"输出 CSV:    {output_csv}")
    print(f"输出 Excel:  {output_xlsx}")
    print(f"参考答案:    {EVAL_DIR / 'PICO6.xlsx'}")
    print("=" * 60)
    print()

    # 模仿前端: 通过 subprocess 调用 EnhancedDataExtraction.py
    # 设置 PYTHONUTF8=1 解决 Windows GBK 编码无法输出 emoji/特殊字符的问题
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    print(f"🚀 开始提取 {len(pdf_files)} 篇论文...")
    print(f"命令: {' '.join(cmd)}\n")

    process = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8")

    # 输出 stdout
    if process.stdout:
        print(process.stdout)

    # 检查结果（与 app.py 逻辑一致）
    if process.returncode != 0:
        error_msg = process.stderr.strip() or process.stdout.strip()
        print(f"\n❌ 提取失败！返回码: {process.returncode}")
        print(f"错误信息:\n{error_msg}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ 提取完成")
    print("=" * 60)
    print(f"结果文件:  {output_xlsx}")
    print(f"请人工对比: {EVAL_DIR / 'PICO6.xlsx'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
