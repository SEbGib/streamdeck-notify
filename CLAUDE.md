# Stream Deck Notify — StreamController Plugin

## Architecture

- **Bridge** (`src/bridge.py`): aiohttp daemon hors Flatpak, poll les sources, expose `/status` + `/events` (SSE)
- **Plugin** (`streamcontroller-plugin/`): dans Flatpak StreamController, affiche les états sur le deck
- **Transport**: SSE temps réel (activé automatiquement au premier contact HTTP)

## StreamController Internals (à respecter)

### Page Switch — PATTERN VALIDÉ

```python
import threading
threading.Timer(0.05, self._do_switch, args=[page_name]).start()

def _do_switch(self):
    import globals as gl
    import time
    page_path = gl.page_manager.get_best_page_path_match_from_name(target)
    page = gl.page_manager.get_page(page_path, self.deck_controller)
    dc = self.deck_controller
    mp = dc.media_player
    dc.active_page = page
    mp.tasks.clear()
    mp.image_tasks.clear()
    dc.load_background(page, update=False)
    dc.load_brightness(page)
    dc.load_all_inputs(page, update=True)

    # CRITIQUE: chaque on_ready dans son propre thread
    # call_actions_ready_and_set_flag() est synchrone et séquentiel.
    # Si un on_ready bloque (subprocess, set_media lent), il bloque
    # TOUS les on_ready suivants → écran noir.
    for action in page.get_all_actions():
        if hasattr(action, "on_ready") and not action.on_ready_called:
            action.on_ready_called = True
            action.load_event_overrides()
            threading.Thread(target=action.on_ready, daemon=True).start()

    dc.update_all_inputs()
    time.sleep(0.5)
    dc.update_all_inputs()
    time.sleep(0.5)       # 2e attente pour les on_ready threads lents
    dc.update_all_inputs()
```

### Page Switch — CE QUI NE FONCTIONNE PAS

- `dc.load_page()` : appelle `clear_media_player_tasks()` qui busy-wait `media_ticks` sans timeout → **bloque indéfiniment** depuis un Timer thread
- `dc.clear()` depuis un media player task : écrit au hardware USB pendant que le media player écrit aussi → **deadlock USB**
- `GLib.idle_add()` pour page switch : le callback ne se déclenche jamais
- `page.call_actions_ready_and_set_flag()` synchrone : itère séquentiellement les actions et appelle on_ready. **Si un on_ready est lent (subprocess, set_media), il bloque les suivants** → seule la 1ère action s'affiche, le reste est noir
- `page.call_actions_ready_and_set_flag()` dans un thread séparé : le on_ready bloquant empêche les actions suivantes d'être marquées ready → mêmes symptômes

### Contraintes identifiées

- **`on_tick()` cross-page** : SC appelle on_tick sur TOUTES les actions chargées, pas seulement la page active. → Toujours commencer on_tick par : `if self.page is not self.deck_controller.active_page: return`
- **`raise Warning("not ready")`** : `set_label()`, `set_media()`, etc. lèvent Warning (pas Exception) si appelés avant on_ready. → Wrapper dans `try/except Warning` partout (on_ready, on_tick, _on_press)
- **`image_tasks`** : traités sans vérification de page, contrairement aux `tasks`. Ne pas clear() entre deux update_all_inputs sinon on efface les images fraîchement rendues
- **MediaPlayerThread** : tourne à 30 FPS, traite `tasks` (avec check page) et `image_tasks` (sans check). Pause = images jamais écrites
- **USB transport** : HID mutex. Ne jamais écrire au deck depuis plusieurs threads simultanément
- **`flatpak-spawn --host`** : fonctionne depuis les actions pour lancer des commandes host (wpctl, xdg-open, google-chrome)
- **subprocess dans on_ready** : ÉVITER. Peut bloquer l'initialisation de la page. Utiliser on_tick pour le premier poll/subprocess
- **on_ready léger** : on_ready doit être rapide. Tout travail lourd (subprocess, réseau, gros rendu PIL) → on_tick ou thread séparé

### Event Assignments

- `Key Down` : se déclenche immédiatement à l'appui (AVANT Hold Start)
- `Key Hold Start` : se déclenche après un délai de maintien
- `Key Short Up` : se déclenche au relâchement SI pas hold
- **Pour hold → page switch** : utiliser `Key Short Up` pour l'action normale et `Key Hold Start` pour le switch. Ne PAS mettre l'action normale sur `Key Down` sinon elle se déclenche aussi sur hold

## Current State

### Fonctionnel
- SSE temps réel (Slack D-Bus instantané, Spotify <5s)
- Page Home ↔ Page2 ↔ Meeting ↔ Music (page switch avec on_ready threaded)
- Hold long sur Agenda → Meeting, Hold long sur Spotify → Music
- Auto-switch Calendar MAINTENANT → Meeting page
- Tous les plugins : Slack, Gmail, Calendar, GitLab, GitHub, CI/CD, Docker, Weather, Spotify, System CPU/RAM
- MediaControlAction (prev/next/play_pause via MPRIS2 bridge)
- MicMuteAction (toggle micro via wpctl)
- VolumeAction (+/- volume via wpctl)
- PomodoroAction
- PWA detection et lancement

### Connu / Minor
- Label résiduel possible au retour sur Home (se corrige au prochain on_tick ~1s). Causé par les on_ready threads qui finissent après le premier update_all_inputs

## Fichiers clés
- `streamcontroller-plugin/actions/NotifyAction.py` — action principale, page switch, meeting auto-switch
- `streamcontroller-plugin/actions/PageSwitchAction.py` — navigation entre pages
- `streamcontroller-plugin/actions/MicMuteAction.py` — toggle micro (wpctl via flatpak-spawn)
- `streamcontroller-plugin/actions/VolumeAction.py` — volume +/- (wpctl via flatpak-spawn)
- `streamcontroller-plugin/actions/MediaControlAction.py` — contrôle media MPRIS2
- `streamcontroller-plugin/internal/bridge_client.py` — client HTTP + SSE
- `src/bridge.py` — bridge aiohttp
- `src/plugins/base.py` — BasePlugin avec notify_state_changed()
- SC source (read-only) : `/app/bin/StreamController/src/backend/DeckManagement/DeckController.py`
- SC Page source : `/app/bin/StreamController/src/backend/PageManagement/Page.py`
