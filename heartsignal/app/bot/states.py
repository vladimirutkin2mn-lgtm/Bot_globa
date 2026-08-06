"""Transient aiogram FSM hints; durable progress remains in PostgreSQL."""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_age = State()
    waiting_for_consent = State()


class IntakeStates(StatesGroup):
    waiting_for_conversation = State()
    waiting_for_goal = State()


class PaymentStates(StatesGroup):
    waiting_for_receipt_contact = State()


class TarotStates(StatesGroup):
    waiting_for_question = State()
    waiting_for_context = State()
    generating = State()


class MemoryStates(StatesGroup):
    waiting_for_correction = State()
