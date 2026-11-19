"""Owner-scoped agent control center API: plans, executions, approvals, tools, workflows."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import agent_orchestrator, workflow_library
from app.agents.monitoring import event_manager, execution_logger, task_monitor
from app.database.db import get_db
from app.models.agent import AgentApproval, AgentExecution, AgentPlan, ExecutionEvent
from app.models.user import User
from app.schemas.agent import (
    AnalyticsResponse,
    ApprovalDecisionRequest,
    ApprovalPage,
    ApprovalResponse,
    EventPage,
    EventResponse,
    ExecutePlanRequest,
    ExecutionPage,
    ExecutionResponse,
    InvocationResponse,
    PlanApproveRequest,
    PlanCreateRequest,
    PlanPage,
    PlanResponse,
    PlanUpdateRequest,
    ToolResponse,
    VerificationPage,
    WorkflowCreateRequest,
    WorkflowDuplicateRequest,
    WorkflowExecuteRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from app.services.session_service import get_current_user

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
@router.post("/plan", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    plan = agent_orchestrator.create_plan(
        db,
        user.user_id,
        payload.objective,
        documents=[item.model_dump() for item in payload.documents],
        title=payload.title,
        priority=payload.priority,
    )
    return PlanResponse(**task_monitor.plan_payload(db, plan))


@router.get("/plans", response_model=PlanPage)
def list_plans(
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanPage:
    plans = agent_orchestrator.list_plans(
        db, user.user_id, status_filter=status_filter, limit=limit, offset=offset
    )
    statement = select(func.count()).select_from(AgentPlan).where(AgentPlan.user_id == user.user_id)
    if status_filter:
        statement = statement.where(AgentPlan.status == status_filter)
    total = db.scalar(statement) or 0
    return PlanPage(
        items=[PlanResponse(**task_monitor.plan_payload(db, plan)) for plan in plans],
        total=int(total),
    )


@router.get("/plans/{plan_id}", response_model=PlanResponse)
def get_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    plan = agent_orchestrator.get_plan(db, user.user_id, plan_id)
    return PlanResponse(**task_monitor.plan_payload(db, plan))


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
def update_plan(
    plan_id: UUID,
    payload: PlanUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    plan = agent_orchestrator.update_plan(
        db,
        user.user_id,
        plan_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        tasks=[task.model_dump() for task in payload.tasks] if payload.tasks is not None else None,
    )
    return PlanResponse(**task_monitor.plan_payload(db, plan))


@router.post("/plans/{plan_id}/approve", response_model=PlanResponse)
def approve_plan(
    plan_id: UUID,
    payload: PlanApproveRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    plan = agent_orchestrator.approve_plan(
        db,
        user.user_id,
        plan_id,
        answers=[item.model_dump() for item in payload.answers] if payload else [],
    )
    return PlanResponse(**task_monitor.plan_payload(db, plan))


@router.delete("/plans/{plan_id}", response_model=PlanResponse)
def archive_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    plan = agent_orchestrator.archive_plan(db, user.user_id, plan_id)
    return PlanResponse(**task_monitor.plan_payload(db, plan))


# --------------------------------------------------------------------------- #
# Executions
# --------------------------------------------------------------------------- #
@router.post("/execute", response_model=ExecutionResponse, status_code=status.HTTP_201_CREATED)
def execute_plan(
    payload: ExecutePlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = agent_orchestrator.start_execution(db, user.user_id, payload.plan_id)
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


@router.get("/executions", response_model=ExecutionPage)
def list_executions(
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionPage:
    executions = agent_orchestrator.list_executions(
        db, user.user_id, status_filter=status_filter, limit=limit, offset=offset
    )
    statement = (
        select(func.count())
        .select_from(AgentExecution)
        .where(AgentExecution.user_id == user.user_id)
    )
    if status_filter:
        statement = statement.where(AgentExecution.status == status_filter)
    total = db.scalar(statement) or 0
    return ExecutionPage(
        items=[
            ExecutionResponse(**task_monitor.execution_payload(db, execution))
            for execution in executions
        ],
        total=int(total),
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
def get_execution(
    execution_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = agent_orchestrator.get_execution(db, user.user_id, execution_id)
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


@router.post("/executions/{execution_id}/pause", response_model=ExecutionResponse)
def pause_execution(
    execution_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = agent_orchestrator.pause_execution(db, user.user_id, execution_id)
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


@router.post("/executions/{execution_id}/resume", response_model=ExecutionResponse)
def resume_execution(
    execution_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = agent_orchestrator.resume_execution(db, user.user_id, execution_id)
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionResponse)
def cancel_execution(
    execution_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = agent_orchestrator.cancel_execution(db, user.user_id, execution_id)
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


@router.get("/executions/{execution_id}/events", response_model=EventPage)
def list_events(
    execution_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EventPage:
    agent_orchestrator.get_execution(db, user.user_id, execution_id)
    events = event_manager.list_events(
        db, user.user_id, execution_id, limit=limit, offset=offset
    )
    total = db.scalar(
        select(func.count())
        .select_from(ExecutionEvent)
        .where(
            ExecutionEvent.user_id == user.user_id,
            ExecutionEvent.execution_id == execution_id,
        )
    ) or 0
    return EventPage(
        items=[EventResponse(**task_monitor.event_payload(event)) for event in events],
        total=int(total),
    )


@router.get("/executions/{execution_id}/verification", response_model=VerificationPage)
def list_verifications(
    execution_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VerificationPage:
    rows = agent_orchestrator.list_verifications(db, user.user_id, execution_id)
    return VerificationPage(
        items=[task_monitor.verification_payload(row) for row in rows],
        total=len(rows),
    )


@router.get("/executions/{execution_id}/invocations", response_model=list[InvocationResponse])
def list_invocations(
    execution_id: UUID,
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InvocationResponse]:
    agent_orchestrator.get_execution(db, user.user_id, execution_id)
    rows = execution_logger.recent_invocations(
        db, user.user_id, limit=limit, execution_id=execution_id
    )
    return [InvocationResponse(**task_monitor.invocation_payload(row)) for row in rows]


# --------------------------------------------------------------------------- #
# Tools and approvals
# --------------------------------------------------------------------------- #
@router.get("/tools", response_model=list[ToolResponse])
def list_tools(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ToolResponse]:
    return [ToolResponse(**tool) for tool in agent_orchestrator.list_tools(db, user.user_id)]


@router.get("/approvals", response_model=ApprovalPage)
def list_approvals(
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalPage:
    rows = agent_orchestrator.list_approvals(
        db, user.user_id, status_filter=status_filter, limit=limit, offset=offset
    )
    statement = (
        select(func.count()).select_from(AgentApproval).where(AgentApproval.user_id == user.user_id)
    )
    if status_filter:
        statement = statement.where(AgentApproval.status == status_filter)
    total = db.scalar(statement) or 0
    return ApprovalPage(
        items=[ApprovalResponse(**task_monitor.approval_payload(row)) for row in rows],
        total=int(total),
    )


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
def approve_action(
    approval_id: UUID,
    payload: ApprovalDecisionRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalResponse:
    approval = agent_orchestrator.decide_approval(
        db, user.user_id, approval_id, approve=True, note=payload.note if payload else None
    )
    return ApprovalResponse(**task_monitor.approval_payload(approval))


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
def reject_action(
    approval_id: UUID,
    payload: ApprovalDecisionRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalResponse:
    approval = agent_orchestrator.decide_approval(
        db, user.user_id, approval_id, approve=False, note=payload.note if payload else None
    )
    return ApprovalResponse(**task_monitor.approval_payload(approval))


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #
@router.get("/workflows", response_model=list[WorkflowResponse])
def list_workflows(
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkflowResponse]:
    return [
        WorkflowResponse(**item)
        for item in workflow_library.list_workflows(db, user.user_id, status_filter=status_filter)
    ]


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    template = workflow_library.create_workflow(
        db,
        user.user_id,
        name=payload.name,
        description=payload.description,
        objective_template=payload.objective_template,
        intent=payload.intent,
        steps=[step.model_dump() for step in payload.steps],
        status=payload.status,
    )
    available, missing = workflow_library._available_tools(list(template.steps or []))
    body = task_monitor.workflow_payload(template)
    body.update({"available": available, "missing_tools": missing, "editable": True})
    return WorkflowResponse(**body)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    template = workflow_library.update_workflow(
        db,
        user.user_id,
        workflow_id,
        name=payload.name,
        description=payload.description,
        objective_template=payload.objective_template,
        intent=payload.intent,
        steps=[step.model_dump() for step in payload.steps] if payload.steps is not None else None,
        status=payload.status,
    )
    available, missing = workflow_library._available_tools(list(template.steps or []))
    body = task_monitor.workflow_payload(template)
    body.update(
        {"available": available, "missing_tools": missing, "editable": template.source != "builtin"}
    )
    return WorkflowResponse(**body)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    workflow_library.delete_workflow(db, user.user_id, workflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/workflows/{workflow_id}/duplicate",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_workflow(
    workflow_id: UUID,
    payload: WorkflowDuplicateRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    template = workflow_library.duplicate_workflow(
        db, user.user_id, workflow_id, name=payload.name if payload else None
    )
    available, missing = workflow_library._available_tools(list(template.steps or []))
    body = task_monitor.workflow_payload(template)
    body.update({"available": available, "missing_tools": missing, "editable": True})
    return WorkflowResponse(**body)


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
)
def execute_workflow(
    workflow_id: UUID,
    payload: WorkflowExecuteRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = workflow_library.execute_workflow(
        db, user.user_id, workflow_id, objective=payload.objective if payload else None
    )
    return ExecutionResponse(**task_monitor.execution_payload(db, execution))


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
@router.get("/analytics", response_model=AnalyticsResponse)
def get_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyticsResponse:
    return AnalyticsResponse(**agent_orchestrator.analytics(db, user.user_id))
