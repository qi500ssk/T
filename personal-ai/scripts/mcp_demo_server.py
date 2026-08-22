"""Minimal stdio MCP server used to verify the P4 integration."""

import random

from mcp.server.fastmcp import FastMCP


server = FastMCP("personal-ai-demo", log_level="WARNING")


@server.tool()
def echo(text: str) -> str:
    """Return the provided text unchanged."""
    return text


@server.tool()
def random_number(min: int, max: int) -> str:
    """Return a random integer inside the inclusive range."""
    if min > max:
        raise ValueError("min must be less than or equal to max")
    return str(random.randint(min, max))


if __name__ == "__main__":
    server.run(transport="stdio")
