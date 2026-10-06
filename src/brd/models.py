from dataclasses import dataclass


@dataclass
class Project:
    id: str
    name: str
    root_path: str
    created_at: str


@dataclass
class Card:
    id: str
    title: str
    description: str | None
    status: str
    parent_id: str | None
    created_at: str
    updated_at: str
