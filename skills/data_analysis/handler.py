"""
Data Analysis Skill Handler

对结构化数据进行统计分析。
"""

import json
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import numpy as np
from scipy import stats


def run(data: str, analysis_type: str = "descriptive", data_format: str = "json",
        target_column: Optional[str] = None, group_by: Optional[str] = None,
        include_charts: bool = True) -> Dict[str, Any]:
    """
    执行数据分析

    Args:
        data: 待分析的数据（JSON 或 CSV 字符串）
        analysis_type: 分析类型
        data_format: 数据格式 (json/csv)
        target_column: 目标列名
        group_by: 分组字段
        include_charts: 是否包含图表配置

    Returns:
        分析结果字典
    """
    try:
        # 解析数据
        df = _parse_data(data, data_format)
        if df is None or df.empty:
            return {"success": False, "error": "数据为空或解析失败"}

        # 执行分析
        if analysis_type == "descriptive":
            result = _descriptive_analysis(df, target_column, group_by)
        elif analysis_type == "trend":
            result = _trend_analysis(df, target_column, group_by)
        elif analysis_type == "correlation":
            result = _correlation_analysis(df, target_column)
        elif analysis_type == "outlier":
            result = _outlier_detection(df, target_column)
        else:
            return {"success": False, "error": f"不支持的分析类型: {analysis_type}"}

        # 添加图表配置
        if include_charts:
            result["charts"] = _generate_chart_config(df, analysis_type, target_column)

        result["success"] = True
        result["row_count"] = len(df)
        result["column_count"] = len(df.columns)

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


def _parse_data(data: str, data_format: str) -> Optional[pd.DataFrame]:
    """解析数据为 DataFrame"""
    try:
        if data_format == "json":
            data_dict = json.loads(data)
            if isinstance(data_dict, list):
                return pd.DataFrame(data_dict)
            elif isinstance(data_dict, dict):
                # 尝试找到数据数组
                for key in ["data", "records", "results", "items"]:
                    if key in data_dict and isinstance(data_dict[key], list):
                        return pd.DataFrame(data_dict[key])
                return pd.DataFrame([data_dict])
        elif data_format == "csv":
            from io import StringIO
            return pd.read_csv(StringIO(data))
    except Exception as e:
        raise ValueError(f"数据解析失败: {e}")
    return None


def _descriptive_analysis(df: pd.DataFrame, target_column: Optional[str],
                          group_by: Optional[str]) -> Dict[str, Any]:
    """描述性统计分析"""
    result = {"analysis_type": "descriptive"}

    if target_column and target_column in df.columns:
        col = df[target_column]
        result["target_column"] = target_column

        # 数值类型统计
        if pd.api.types.is_numeric_dtype(col):
            result["statistics"] = {
                "count": int(col.count()),
                "mean": float(col.mean()) if col.count() > 0 else None,
                "median": float(col.median()) if col.count() > 0 else None,
                "std": float(col.std()) if col.count() > 0 else None,
                "min": float(col.min()) if col.count() > 0 else None,
                "max": float(col.max()) if col.count() > 0 else None,
                "quartiles": {
                    "q1": float(col.quantile(0.25)) if col.count() > 0 else None,
                    "q2": float(col.quantile(0.50)) if col.count() > 0 else None,
                    "q3": float(col.quantile(0.75)) if col.count() > 0 else None,
                }
            }

        # 分组统计
        if group_by and group_by in df.columns:
            grouped = df.groupby(group_by)[target_column].agg(["count", "mean", "std"])
            result["grouped"] = grouped.to_dict("index")

    # 整体数据概览
    result["overview"] = {
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_values": df.isnull().sum().to_dict(),
    }

    return result


def _trend_analysis(df: pd.DataFrame, target_column: Optional[str],
                    group_by: Optional[str]) -> Dict[str, Any]:
    """趋势分析"""
    result = {"analysis_type": "trend"}

    if not target_column or target_column not in df.columns:
        return {"error": "请指定有效的目标列"}

    col = df[target_column]
    result["target_column"] = target_column

    # 简单趋势：计算相邻变化率
    if pd.api.types.is_numeric_dtype(col):
        values = col.dropna().values
        if len(values) > 1:
            changes = np.diff(values)
            result["trend"] = {
                "direction": "up" if changes.sum() > 0 else "down" if changes.sum() < 0 else "flat",
                "change_rate": float((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0,
                "volatility": float(np.std(changes)),
            }

    return result


def _correlation_analysis(df: pd.DataFrame, target_column: Optional[str]) -> Dict[str, Any]:
    """相关性分析"""
    result = {"analysis_type": "correlation"}

    # 只分析数值列
    numeric_df = df.select_dtypes(include=[np.number])

    if numeric_df.empty:
        return {"error": "没有数值列可用于相关性分析"}

    # 计算相关系数矩阵
    corr_matrix = numeric_df.corr()

    result["correlation_matrix"] = corr_matrix.to_dict()

    # 如果指定了目标列，找出相关性最高的列
    if target_column and target_column in corr_matrix.columns:
        correlations = corr_matrix[target_column].drop(target_column).abs().sort_values(ascending=False)
        result["top_correlations"] = correlations.head(5).to_dict()

    return result


def _outlier_detection(df: pd.DataFrame, target_column: Optional[str]) -> Dict[str, Any]:
    """异常值检测"""
    result = {"analysis_type": "outlier"}

    columns_to_check = [target_column] if target_column else df.select_dtypes(include=[np.number]).columns.tolist()

    outliers = {}

    for col in columns_to_check:
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            continue

        values = df[col].dropna()
        if len(values) < 4:
            continue

        # IQR 方法检测异常值
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        outlier_mask = (values < lower) | (values > upper)
        outlier_indices = values[outlier_mask].index.tolist()

        outliers[col] = {
            "count": len(outlier_indices),
            "indices": outlier_indices,
            "bounds": {"lower": float(lower), "upper": float(upper)},
        }

    result["outliers"] = outliers
    return result


def _generate_chart_config(df: pd.DataFrame, analysis_type: str,
                           target_column: Optional[str]) -> List[Dict]:
    """生成图表配置（ECharts 格式）"""
    charts = []

    if target_column and target_column in df.columns:
        if analysis_type == "descriptive" and pd.api.types.is_numeric_dtype(df[target_column]):
            # 直方图
            charts.append({
                "type": "histogram",
                "title": f"{target_column} 分布",
                "xAxis": {"type": "category", "data": "bins"},
                "yAxis": {"type": "value"},
                "series": [{"type": "bar", "data": "counts"}]
            })

        elif analysis_type == "trend":
            # 折线图
            charts.append({
                "type": "line",
                "title": f"{target_column} 趋势",
                "xAxis": {"type": "category", "data": "index"},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": f"{target_column}_values"}]
            })

    return charts


if __name__ == "__main__":
    # 测试
    test_data = json.dumps([
        {"name": "A", "value": 10},
        {"name": "B", "value": 20},
        {"name": "C", "value": 15},
        {"name": "D", "value": 25},
        {"name": "E", "value": 18},
    ])

    result = run(
        data=test_data,
        analysis_type="descriptive",
        data_format="json",
        target_column="value"
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
