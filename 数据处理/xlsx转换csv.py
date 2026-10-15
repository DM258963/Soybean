# xlsx_to_csv.py
import pandas as pd

# 1) 在这里填写输入 xlsx 路径
INPUT_XLSX = r"E:\Project\网站\data\网站gs数据-V1-260423.xlsx"

# 2) 在这里填写输出 csv 路径
OUTPUT_CSV = r"E:\Project\网站\data\网站gs数据-V1-260423.csv"

# 3) 工作表：可填 0（第一个）、1（第二个）或表名字符串
SHEET = 0


def main() -> None:
    df = pd.read_excel(INPUT_XLSX, sheet_name=SHEET, engine="openpyxl", dtype=object)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Done: {INPUT_XLSX} -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
