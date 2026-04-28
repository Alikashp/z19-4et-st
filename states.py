from aiogram.fsm.state import State, StatesGroup


class ReportStates(StatesGroup):
    choosing_input_type = State()
    waiting_for_topic = State()
    waiting_for_text = State()
    waiting_for_document = State()
    choosing_level = State()
    choosing_volume = State()
    confirming = State()
    generating = State()


class AbstractStates(StatesGroup):
    choosing_input_type = State()
    waiting_for_topic = State()
    waiting_for_text = State()
    waiting_for_document = State()
    choosing_level = State()
    choosing_volume = State()
    confirming = State()
    generating = State()


class PresentationStates(StatesGroup):
    choosing_input_type = State()
    waiting_for_topic = State()
    waiting_for_text = State()
    settings = State()
    choosing_language = State()
    choosing_slides_count = State()
    choosing_design = State()
    generating = State()


class SourcesStates(StatesGroup):
    choosing_variant = State()
    # "По теме" branch
    waiting_for_topic = State()
    choosing_format = State()
    choosing_count = State()
    # "Оформить свои" branch
    waiting_for_sources = State()
    choosing_own_format = State()
    generating = State()


class SpeechStates(StatesGroup):
    generating = State()


class QAStates(StatesGroup):
    generating = State()
