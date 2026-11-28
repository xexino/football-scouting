"""MCP server definition (tool schemas + transport glue). Security lives in ``gateway``.

Input validation: every argument has a type, range, length or enumeration in its JSON
schema; the SDK validates before the handler runs, and the underlying endpoint validates
again. There is no free-form query or SQL tool.

Write tools are registered only when ``MCP_WRITE_TOOLS_ENABLED=true``. Each one needs
explicit approval from the human user through MCP *elicitation* (a confirmation dialog shown
by the MCP client). Approval is not a tool argument, so the model cannot approve its own
action; a client without elicitation support is refused.
"""

import hashlib
import inspect
import json
from functools import partial
from typing import Annotated, Callable, Literal

import anyio
from pydantic import BaseModel, Field

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as SDKToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp.server.request_state import RequestStateSecurity
from mcp.types import ToolAnnotations

from ..analytics import METRICS, TACTICAL_ROLES
from ..config import settings
from ..models import (GAME_PHASES, OBSERVATION_ASSESSMENTS, OBSERVATION_CATEGORIES, PIPELINE_STAGES, POSITIONS,
                      PRIORITIES)
from . import gateway
from .tools import READ_TOOLS, WRITE_TOOLS

TokenSource = Callable[[], "str | None"]

Position = Literal[POSITIONS]  # type: ignore[valid-type]
Metric = Literal[tuple(METRICS)]  # type: ignore[valid-type]
Stage = Literal[PIPELINE_STAGES]  # type: ignore[valid-type]
Priority = Literal[PRIORITIES]  # type: ignore[valid-type]
Role = Literal[tuple(TACTICAL_ROLES)]  # type: ignore[valid-type]
Category = Literal[OBSERVATION_CATEGORIES]  # type: ignore[valid-type]
Phase = Literal[GAME_PHASES]  # type: ignore[valid-type]
Assessment = Literal[OBSERVATION_ASSESSMENTS]  # type: ignore[valid-type]

Id = Annotated[int, Field(ge=1, le=2_147_483_647)]
Season = Annotated[str, Field(pattern=r"^(\d{4}(-\d{2})?|all)$", description="e.g. 2025-26, 2025, or 'all'")]
ShortText = Annotated[str, Field(min_length=1, max_length=80)]
Age = Annotated[int, Field(ge=14, le=45)]
Minutes = Annotated[int, Field(ge=0, le=10_000)]
StatFilters = Annotated[str, Field(max_length=300, pattern=r"^[a-z0-9_]+\s*(>=|<=|>|<|=)\s*-?\d+(\.\d+)?"
                                                          r"(\s*,\s*[a-z0-9_]+\s*(>=|<=|>|<|=)\s*-?\d+(\.\d+)?)*$",
                                   description="Latest-season metric filters, e.g. 'prog_passes_p90>=4,pass_pct>=80'")]
SortKey = Annotated[str, Field(pattern=r"^(full_name|age|contract_expiry|last_updated|height|metric:[a-z0-9_]+)$")]

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Raja Scout Intelligence tools for the signed-in user's club. Data is limited to what the user's role may see. "
    "Fields under 'organisation_private' are the club's confidential assessments: never send them to other tools "
    "or external data providers. Statistics describe recorded past output; never present a player as a certain "
    "future star, and never invent statistics or scouting observations."
)


def _tool_args(spec, args: dict) -> dict:
    """Only the tool function's declared parameters (handlers pass ``locals()``), minus unset ones."""
    allowed = set(inspect.signature(spec.fn).parameters) - {"ctx", "db"}
    return {k: v for k, v in args.items() if k in allowed and v is not None}


class Approval(BaseModel):
    approve: bool = Field(description="Approve this action?")


def build_server(token_source: TokenSource, *, transport: str, write_tools: bool | None = None,
                 **server_kwargs) -> MCPServer:
    # request_state (approval round-trips) is sealed with a key derived from SECRET_KEY, 5-minute TTL
    state_key = hashlib.sha256(b"raja-scout-mcp-request-state:" + settings.secret_key.encode()).digest()
    mcp = MCPServer("raja-scout", instructions=INSTRUCTIONS,
                    request_state_security=RequestStateSecurity(keys=[state_key], ttl=300), **server_kwargs)

    async def run(name: str, args: dict) -> dict:
        spec = READ_TOOLS[name]
        clean = _tool_args(spec, args)
        return await anyio.to_thread.run_sync(
            partial(gateway.invoke, spec, clean, token_source(), transport=transport))

    def read_tool(fn):
        spec = READ_TOOLS[fn.__name__]
        return mcp.tool(name=spec.name, description=spec.description, annotations=READ)(fn)

    @read_tool
    async def search_players(
            query: Annotated[str, Field(max_length=80, description="Name contains")] | None = None,
            positions: Annotated[list[Position], Field(max_length=8)] | None = None,
            primary_only: bool = False, age_min: Age | None = None, age_max: Age | None = None,
            nationality: ShortText | None = None, league_country: ShortText | None = None,
            min_minutes: Minutes | None = None, stat_filters: StatFilters | None = None,
            sort: SortKey = "full_name", order: Literal["asc", "desc"] = "asc",
            page: Annotated[int, Field(ge=1, le=1000)] = 1, page_size: Annotated[int, Field(ge=1, le=50)] = 25,
            include_private_assessment: bool = False) -> dict:
        return await run("search_players", locals())

    @read_tool
    async def get_player_profile(player_id: Id, include_private_assessment: bool = False) -> dict:
        return await run("get_player_profile", locals())

    @read_tool
    async def get_player_statistics(player_id: Id, season: Season | None = None) -> dict:
        return await run("get_player_statistics", locals())

    @read_tool
    async def find_young_talents(
            max_age: Annotated[int, Field(ge=14, le=23)] = 21,
            positions: Annotated[list[Position], Field(max_length=8)] | None = None,
            metric: Metric = "prog_passes_p90", min_minutes: Minutes = 450,
            nationality: ShortText | None = None, league_country: ShortText | None = None,
            limit: Annotated[int, Field(ge=1, le=50)] = 15) -> dict:
        return await run("find_young_talents", locals())

    @read_tool
    async def compare_players(player_ids: Annotated[list[Id], Field(min_length=2, max_length=5)],
                              season: Season | None = None, tactical_role: Role | None = None,
                              allow_mixed_positions: bool = False) -> dict:
        return await run("compare_players", locals())

    @read_tool
    async def get_club_requirements() -> dict:
        return await run("get_club_requirements", {})

    @read_tool
    async def get_recruitment_pipeline(stage: Stage | None = None, priority: Priority | None = None,
                                       position: Position | None = None, assigned_to_me: bool = False,
                                       player_id: Id | None = None) -> dict:
        return await run("get_recruitment_pipeline", locals())

    @read_tool
    async def get_scouting_reports(player_id: Id | None = None, report_id: Id | None = None) -> dict:
        return await run("get_scouting_reports", locals())

    @read_tool
    async def generate_shortlist(position: Position,
                                 metrics: Annotated[list[Metric], Field(min_length=1, max_length=4)],
                                 max_age: Age | None = None, min_minutes: Minutes = 900,
                                 exclude_in_pipeline: bool = True,
                                 limit: Annotated[int, Field(ge=1, le=20)] = 10) -> dict:
        return await run("generate_shortlist", locals())

    if write_tools if write_tools is not None else settings.mcp_write_tools_enabled:
        _register_write_tools(mcp, token_source, transport)
    return mcp


def _register_write_tools(mcp: MCPServer, token_source: TokenSource, transport: str) -> None:
    """Write tools: preview (authorise + describe) -> human approval via elicitation -> execute.

    The approval is requested by an SDK *resolver*, which works with both protocol generations
    (a standalone ``elicitation/create`` request on <= 2025-11-25, an ``InputRequiredResult`` on
    >= 2026-07-28, whose ``request_state`` is sealed and bound to the request by the SDK).
    A client that cannot elicit is refused by the SDK before the tool runs (fail closed).
    """

    async def preview(name: str, args: dict) -> Elicit[Approval]:
        spec = WRITE_TOOLS[name]
        result = await anyio.to_thread.run_sync(
            partial(gateway.invoke, spec, _tool_args(spec, args), token_source(), transport=transport,
                    phase="preview"))
        if "error" in result:  # not authorised / invalid: abort before asking the human anything
            raise SDKToolError(json.dumps(result))
        message = result["action"]
        if result.get("warnings"):
            message += " Warnings: " + "; ".join(result["warnings"])
        return Elicit(message + " Approve this change in Raja Scout?", Approval)

    async def run_write(name: str, args: dict, approval: ElicitationResult[Approval]) -> dict:
        spec = WRITE_TOOLS[name]
        clean, token = _tool_args(spec, args), token_source()
        if not isinstance(approval, AcceptedElicitation) or not approval.data.approve:
            outcome = approval.action if not isinstance(approval, AcceptedElicitation) else "answered_no"
            await anyio.to_thread.run_sync(partial(gateway.record, token, spec, clean, "mcp.write_declined",
                                                   outcome, transport))
            return {"error": "declined", "message": "The user did not approve this action. Nothing was changed."}
        # re-authenticated and re-authorised inside invoke
        return await anyio.to_thread.run_sync(
            partial(gateway.invoke, spec, clean, token, transport=transport, approval="human_elicitation"))

    def write_tool(fn):
        spec = WRITE_TOOLS[fn.__name__]
        return mcp.tool(name=spec.name, description=spec.description, annotations=WRITE)(fn)

    async def ask_report(player_id: int, season: str | None = None, tactical_role: str | None = None):
        return await preview("create_scouting_report", locals())

    @write_tool
    async def create_scouting_report(
            player_id: Id,
            approval: Annotated[ElicitationResult[Approval], Resolve(ask_report)],
            season: Season | None = None, tactical_role: Role | None = None) -> dict:
        return await run_write("create_scouting_report", locals(), approval)

    async def ask_observation(video_id: int, timestamp_seconds: int, category: str, assessment: str = "neutral",
                              phase: str | None = None, technical_comment: str | None = None,
                              tactical_comment: str | None = None):
        return await preview("add_video_observation", locals())

    @write_tool
    async def add_video_observation(
            video_id: Id, timestamp_seconds: Annotated[int, Field(ge=0, le=4 * 3600)], category: Category,
            approval: Annotated[ElicitationResult[Approval], Resolve(ask_observation)],
            assessment: Assessment = "neutral", phase: Phase | None = None,
            technical_comment: Annotated[str, Field(max_length=2000)] | None = None,
            tactical_comment: Annotated[str, Field(max_length=2000)] | None = None) -> dict:
        return await run_write("add_video_observation", locals(), approval)

    async def ask_move(entry_id: int, to_stage: str, note: str):
        return await preview("update_recruitment_status", locals())

    @write_tool
    async def update_recruitment_status(
            entry_id: Id, to_stage: Stage, note: Annotated[str, Field(min_length=3, max_length=2000)],
            approval: Annotated[ElicitationResult[Approval], Resolve(ask_move)]) -> dict:
        return await run_write("update_recruitment_status", locals(), approval)
