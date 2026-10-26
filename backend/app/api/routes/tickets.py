import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Message,
    Ticket,
    TicketCreate,
    TicketPublic,
    TicketsPublic,
    TicketStatus,
    TicketUpdate,
    User,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])

ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.open: frozenset({TicketStatus.in_progress}),
    TicketStatus.in_progress: frozenset({TicketStatus.resolved}),
    TicketStatus.resolved: frozenset({TicketStatus.in_progress, TicketStatus.closed}),
    TicketStatus.closed: frozenset(),
}


def _get_ticket(
    session: Session, current_user: User, id: uuid.UUID, *, for_update: bool = False
) -> Ticket:
    if for_update:
        # Serialize writes so concurrent PATCH requests validate the latest status.
        ticket = session.exec(
            select(Ticket)
            .where(Ticket.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
    else:
        ticket = session.get(Ticket, id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not current_user.is_superuser and ticket.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return ticket


@router.post("/", response_model=TicketPublic, status_code=201)
def create_ticket(
    *, session: SessionDep, current_user: CurrentUser, ticket_in: TicketCreate
) -> Ticket:
    """Create an open ticket owned by the authenticated user."""
    ticket = Ticket.model_validate(ticket_in, update={"owner_id": current_user.id})
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@router.get("/", response_model=TicketsPublic)
def read_tickets(
    session: SessionDep,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> TicketsPublic:
    """List accessible tickets and their total count before pagination."""
    statement = select(Ticket)
    count_statement = select(func.count()).select_from(Ticket)
    if not current_user.is_superuser:
        statement = statement.where(Ticket.owner_id == current_user.id)
        count_statement = count_statement.where(Ticket.owner_id == current_user.id)
    count = session.exec(count_statement).one()
    tickets = session.exec(
        statement.order_by(col(Ticket.created_at).desc(), col(Ticket.id).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return TicketsPublic(
        data=[TicketPublic.model_validate(ticket) for ticket in tickets], count=count
    )


@router.get("/{id}", response_model=TicketPublic)
def read_ticket(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Ticket:
    """Read an owned ticket, or any ticket as an administrator."""
    return _get_ticket(session, current_user, id)


@router.patch("/{id}", response_model=TicketPublic)
def update_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    ticket_in: TicketUpdate,
) -> Ticket:
    """Partially update a ticket, enforcing the status graph for every user."""
    ticket = _get_ticket(session, current_user, id, for_update=True)
    if (
        ticket_in.status is not None
        and ticket_in.status != ticket.status
        and ticket_in.status not in ALLOWED_TRANSITIONS[ticket.status]
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid ticket status transition: {ticket.status} -> {ticket_in.status}",
        )
    ticket.sqlmodel_update(ticket_in.model_dump(exclude_unset=True))
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@router.delete("/{id}")
def delete_ticket(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """Delete an accessible ticket."""
    ticket = _get_ticket(session, current_user, id, for_update=True)
    session.delete(ticket)
    session.commit()
    return Message(message="Ticket deleted successfully")
