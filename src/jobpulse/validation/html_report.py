"""jobpulse.validation.html_report — Generates HTML reports."""

import os
from pathlib import Path

from jobpulse.validation.report import ValidationReport


def generate_html_report(report: ValidationReport, output_dir: str = "reports") -> str:
    """Generates an HTML report from a ValidationReport."""
    os.makedirs(output_dir, exist_ok=True)
    report_path = Path(output_dir) / "validation_report.html"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>JobPulse Validation Report</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            h1, h2 {{ color: #2c3e50; }}
            .kpi-board {{ display: flex; gap: 20px; margin-bottom: 30px; }}
            .kpi-card {{ flex: 1; background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center; }}
            .kpi-value {{ font-size: 2em; font-weight: bold; color: #2980b9; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #2980b9; color: white; }}
            tr:hover {{ background-color: #f1f1f1; }}
            .CRITICAL {{ color: #e74c3c; font-weight: bold; }}
            .ERROR {{ color: #e67e22; font-weight: bold; }}
            .WARNING {{ color: #f1c40f; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>JobPulse Data Validation Report</h1>
            <p>Timestamp: {report.timestamp}</p>
            
            <h2>Executive Summary</h2>
            <div class="kpi-board">
                <div class="kpi-card"><div>Rows Checked</div><div class="kpi-value">{report.rows_checked}</div></div>
                <div class="kpi-card"><div>Valid Rows</div><div class="kpi-value" style="color:#27ae60;">{report.rows_valid}</div></div>
                <div class="kpi-card"><div>Invalid Rows</div><div class="kpi-value" style="color:#e74c3c;">{report.rows_invalid}</div></div>
                <div class="kpi-card"><div>Success Rate</div><div class="kpi-value">{report.success_rate:.1%}</div></div>
            </div>
            
            <h2>Performance Metrics</h2>
            <ul>
                <li>Execution Time: {report.execution_time:.2f} seconds</li>
                <li>Processing Speed: {report.rows_per_second:.0f} rows/sec</li>
            </ul>

            <h2>Unknown Skills Identified</h2>
            <p>{', '.join(report.unknown_skills[:20]) if report.unknown_skills else 'None detected.'} { '...' if len(report.unknown_skills) > 20 else '' }</p>
            
            <h2>Rule Execution Summary</h2>
            <table>
                <tr><th>Rule Name</th><th>Severity</th><th>Rows Failed</th><th>Execution Time (s)</th></tr>
    """

    for rule in report.rule_results:
        html_content += f"""
                <tr>
                    <td>{rule.rule_name}</td>
                    <td class="{rule.severity}">{rule.severity}</td>
                    <td>{rule.rows_failed}</td>
                    <td>{rule.execution_time:.3f}</td>
                </tr>
        """

    html_content += """
            </table>
        </div>
    </body>
    </html>
    """

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return str(report_path)
