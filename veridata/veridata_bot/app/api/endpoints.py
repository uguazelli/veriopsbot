from fastapi import APIRouter
from fastcrud import crud_router

from app.core.db import async_session_maker
from app.models import BotSession, Client, ServiceConfig, Subscription
from app.dtos import (
    BotSessionCreate,
    BotSessionRead,
    BotSessionUpdate,
    ClientCreate,
    ClientRead,
    ClientUpdate,
    ServiceConfigCreate,
    ServiceConfigRead,
    ServiceConfigUpdate,
    SubscriptionCreate,
    SubscriptionRead,
    SubscriptionUpdate,
)

router = APIRouter()

# Client CRUD
router.include_router(
    crud_router(
        session=async_session_maker,
        model=Client,
        create_schema=ClientCreate,
        update_schema=ClientUpdate,
        select_schema=ClientRead,
        path="/clients",
        tags=["Clients"],
    )
)

# Subscription CRUD
router.include_router(
    crud_router(
        session=async_session_maker,
        model=Subscription,
        create_schema=SubscriptionCreate,
        update_schema=SubscriptionUpdate,
        select_schema=SubscriptionRead,
        path="/subscriptions",
        tags=["Subscriptions"],
    )
)

# ServiceConfig CRUD
router.include_router(
    crud_router(
        session=async_session_maker,
        model=ServiceConfig,
        create_schema=ServiceConfigCreate,
        update_schema=ServiceConfigUpdate,
        select_schema=ServiceConfigRead,
        path="/configs",
        tags=["Service Configs"],
    )
)

# BotSession CRUD
router.include_router(
    crud_router(
        session=async_session_maker,
        model=BotSession,
        create_schema=BotSessionCreate,
        update_schema=BotSessionUpdate,
        select_schema=BotSessionRead,
        path="/sessions",
        tags=["Bot Sessions"],
    )
)
