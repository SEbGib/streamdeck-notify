"""Shared page-switch utility for StreamController actions."""

from __future__ import annotations

import threading
import time

from loguru import logger as log


def _safe_on_ready(action) -> None:
    """Call on_ready in a thread, catching all errors including Warning."""
    name = action.__class__.__name__
    source = getattr(action, '_source', '?')
    try:
        action.on_ready()
        log.info(f"on_ready OK: {name}({source})")
    except Warning as w:
        log.warning(f"on_ready WARNING: {name}({source}): {w}")
    except Exception as e:
        log.warning(f"on_ready FAIL: {name}({source}): {e}")
    except BaseException as e:
        log.error(f"on_ready CRASH: {name}({source}): {type(e).__name__}: {e}")


def switch_to_page(page_name: str, deck_controller) -> None:
    """Switch the deck to a named page.

    Resolves the page path, loads all page content, calls on_ready for new
    actions only, then re-renders all keys twice with a short sleep between.
    """
    try:
        import globals as gl

        page_path = gl.page_manager.get_best_page_path_match_from_name(page_name)
        if page_path is None:
            log.warning(f"Page '{page_name}' not found")
            return
        page = gl.page_manager.get_page(page_path, deck_controller)
        dc = deck_controller

        # Synchronized clear — waits for current media player tick to finish
        dc.active_page = page
        dc.clear_media_player_tasks()

        # Load page content — update=True forces immediate render of all keys
        # (clears stale images from previous page on empty slots)
        dc.load_background(page, update=True)
        dc.load_brightness(page)
        dc.load_all_inputs(page, update=True)

        # Only call on_ready for NEW actions (first load)
        # Returning pages already have state — just re-render
        threads = []
        for action in page.get_all_actions():
            if hasattr(action, "on_ready") and not action.on_ready_called:
                action.load_event_overrides()
                action.on_ready_called = True
                t = threading.Thread(
                    target=_safe_on_ready,
                    args=(action,),
                    daemon=True,
                )
                t.start()
                threads.append(t)

        for t in threads:
            t.join(timeout=3.0)

        # Flush stale image_tasks from previous page's in-flight on_tick
        dc.clear_media_player_tasks()

        # Re-render all keys — uses stored action state
        dc.update_all_inputs()
        time.sleep(0.3)
        dc.update_all_inputs()

        log.info(f"Switched to page: {page_name}")
    except Exception as e:
        log.error(f"Page switch error: {e}")
