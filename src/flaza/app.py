"""Flaza desktop entrypoint."""

from neony.application import Page, launch
from neony.application.elements import Heading, Text, VStack


def create_page() -> Page:
    """Build the placeholder main window."""
    return Page(gap="16px").add(
        VStack(
            Heading("Flaza", level=1),
            Text("A QQ desktop client built with lagrange-python and Neony.", role="secondary"),
            gap="12px",
        )
    )


def main() -> None:
    """Launch the Flaza desktop app."""
    launch(create_page(), title="Flaza", width=480, height=360, devtools=True)
