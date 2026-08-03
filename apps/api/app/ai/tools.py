"""Typed, authorization-first AI tool registry and execution boundary."""

from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel, ValidationError

from apps.api.app.ai.models import ToolResult
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)

InputT = TypeVar("InputT", bound=BaseModel)


class AgentTool(Protocol[InputT]):
    name: str
    description: str
    input_model: type[InputT]
    required_permission: Permission

    async def authorize(self, context: RequestContext, input_data: InputT) -> None: ...

    async def execute(self, context: RequestContext, input_data: InputT) -> ToolResult: ...


class ToolNotFoundError(LookupError):
    pass


class InvalidToolInputError(ValueError):
    pass


class ToolRegistry:
    def __init__(self, authorization: AuthorizationService) -> None:
        self._authorization = authorization
        self._tools: dict[str, AgentTool[Any]] = {}

    def register(self, tool: AgentTool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self, allowed_names: frozenset[str]) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for name, tool in sorted(self._tools.items())
            if name in allowed_names
        )

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError("Requested tool is not registered")
        try:
            parsed = tool.input_model.model_validate(arguments)
        except ValidationError as error:
            raise InvalidToolInputError("Tool input did not match its approved schema") from error
        if not self._authorization.is_allowed(
            context,
            tool.required_permission,
            AuthorizationResource(tenant_id=context.tenant_id, tool_code=name),
        ):
            raise AuthorizationError("The authenticated user is not permitted to use this tool.")
        await tool.authorize(context, cast("Any", parsed))
        result = await tool.execute(context, cast("Any", parsed))
        return ToolResult.model_validate(result)
