"""自定义 Math MCP 服务：通过 stdio 提供加法、乘法和平方根工具。

由 mcp-customization.py 自动启动，无需手动运行。
单独运行：uv run python demo/math_mcp_server.py（等待客户端通过 stdin 发送请求）。
"""

import math

# 复用项目已安装的 MCP SDK 内置 FastMCP，无需额外安装 fastmcp 包。
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Math")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers. 将两个数相加。"""
    return a + b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers. 将两个数相乘。"""
    return a * b


@mcp.tool()
def square_root(x: float) -> float:
    """Calculate the non-negative square root of a number. 计算非负数的算术平方根。"""
    if x < 0:
        raise ValueError("只能计算非负数的算术平方根，x 不能小于 0。")
    return math.sqrt(x)


if __name__ == "__main__":
    # stdout 用于 MCP 协议通信，不要在服务端用 print 输出调试信息。
    mcp.run(transport="stdio")
