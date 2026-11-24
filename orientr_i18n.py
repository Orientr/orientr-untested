# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Texts of Orientr in English, German and French.

The language is the one saved in the settings (chosen in the form), else the Windows display language when it is
German or French, else English. t("key", name=value) returns the text in that language, English when a text is missing.
"""
import json
import os
import string
import tempfile
from pathlib import Path

LANGS = {"en": "English", "de": "Deutsch", "fr": "Français"}
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "orientr"   # settings, presets and caches
SETTINGS = APP_DIR / "settings.json"
_lang: str | None = None


def _settings() -> dict:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _windows_language() -> str:
    try:
        import ctypes
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF   # primary language id
        return {0x07: "de", 0x0C: "fr"}.get(primary, "en")
    except (OSError, AttributeError):
        return "en"


def language() -> str:
    global _lang
    if _lang is None:
        saved = str(_settings().get("language") or "")
        _lang = saved if saved in LANGS else _windows_language()
    return _lang


def set_language(code: str) -> None:
    """Use this language from now on, also next time (saved in the settings)."""
    global _lang
    if code not in LANGS:
        return
    _lang = code
    save_setting("language", code)


def setting(key: str, default=None):
    """A value from this user's settings (the same for every model): the language, the form's presets."""
    return _settings().get(key, default)


def save_setting(key: str, value) -> bool:
    """Save one value in this user's settings; False when it could not be written."""
    data = _settings()
    data[key] = value
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all (the presets live here too), through a file of its own: two forms never share one
        fd, tmp = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=SETTINGS.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, SETTINGS)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except (OSError, NameError):
            pass
        return False                                      # only the choice for next time is lost


class _Plural(string.Formatter):
    """str.format, plus singular and plural: "{n} {n:plate|plates}" gives "1 plate" and "3 plates" (2026-11-22: the
    report said "1 plate(s)" and "1 ledges")."""

    def format_field(self, value, spec):
        if "|" in spec:
            one, many = spec.split("|", 1)
            return one if str(value).strip() in ("1", "1.0") else many
        return super().format_field(value, spec)


_FORMAT = _Plural()


def t(key: str, **kw) -> str:
    text = STRINGS.get(language(), {}).get(key) or STRINGS["en"].get(key) or key
    try:
        return _FORMAT.format(text, **kw)
    except (KeyError, IndexError, ValueError, AttributeError):
        return text


def cap(text) -> str:
    """The first letter a capital (2026-11-23: every text in the form starts with one), the rest as it is. For texts
    that also stand inside a sentence of the report, such as colour names and error messages."""
    text = str(text)
    return text[:1].upper() + text[1:]


STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # form fields
        "f.printer": "Printer", "f.filament": "Filament", "f.process": "Process", "f.walls": "Walls",
        "f.infill": "Infill", "f.support": "Support", "f.brim": "Brim", "f.parts": "Parts", "f.parts_n": "Parts ({n})",
        "f.open": "Open in Bambu Studio", "f.language": "Language", "f.nozzle": "Nozzle",
        "f.nozzle_size": "Nozzle size",
        "s.printer": "Printer Settings", "s.quality": "Quality Settings",
        "s.volume": "Quantity Settings", "s.other": "Others",
        "v.left": "Left only", "v.right": "Right only", "v.na": "N/A",
        # values
        "v.profile": "As in the preset", "v.wall": "{n} wall", "v.walls": "{n} walls", "v.auto": "Auto (per part)",
        "v.on": "Always", "v.off": "Never", "v.yes": "Yes", "v.no": "No", "v.parts": "{on} of {all}",
        "v.current": "Current",
        # buttons and help
        "b.make": "Generate", "b.cancel": "Cancel",
        "help.form": "↑↓  Field   ←→  Change   Enter List / Button   G A C  Buttons   Esc Cancel",
        "keys.buttons": "GAC",
        "help.list": "↑↓  Choose   A-Z Jump   PgUp/PgDn Page   Enter Select   Esc Back",
        "help.models": "↑↓  Choose   PgUp/PgDn Page   Enter Open   Esc Cancel",
        "pick.model": "Choose a model (newest first)",
        # hints under the form, for the field the cursor is on
        "h.printer": "{n} printers with a template.",
        "h.filament": "{n} presets for this printer. Enter: Full list.",
        "h.process": "Layer height and speed preset.",
        "h.walls": "Or type any number from 1 to 20. Small and snap/load parts get 4+ walls anyway.",
        "h.infill": "Or type any percentage from 0 to 100. Small and snap/load parts get more anyway.",
        "h.support": "Auto: Per part, from its overhangs.",
        "h.brim": "Auto: Per part (tall, small or warping).",
        "h.parts": "Enter: Choose the printed parts, and with ←→  how many of each.",
        "f.duplicates": "Duplicates", "f.max_plates": "Max plates",
        "v.no_limit": "No limit", "v.plate": "1 plate", "v.plates": "{n} plates",
        "h.duplicates": "The whole set this many times (per part: in Parts). Enter, or type a number.",
        "h.max_plates": "More plates needed: The parts are packed tighter; if they still do not fit, nothing is made.",
        "h.nozzle_size": "Sizes this printer supports.",
        "h.nozzle": "Two-nozzle printers: Auto, or force one nozzle.",
        "h.open": "Opens the project in Bambu Studio.",
        "f.prestart": "Background Bambu Studio",
        "h.prestart": "Hidden Bambu Studio: Generate opens faster. Change, then Enter: Start or close it now. "
                      "⚠ Extra load on the PC; at start its banner shows for a few seconds.",
        # 2026-11-23: ←→ only picks, Enter starts or closes it
        "bg.opening": "Opening…", "bg.open": "Open", "bg.closing": "Closing…", "bg.closed": "Closed",
        "n.prestart_on": "Enter: Start Bambu Studio in the background now.",
        "n.prestart_off": "Enter: Close the background Bambu Studio now.",
        "n.prestart_started": "Saved. Bambu Studio starts in the background, as soon as the PC is quiet.",
        "n.prestart_not_started": "Saved. Bambu Studio did not start in the background now (already open, or "
                                  "Open in Bambu Studio is off).",
        "n.prestart_first": "Saved. Bambu Studio cannot start in the background yet: open it yourself once first.",
        "n.prestart_closed": "Saved. The background Bambu Studio closes (one you use stays open).",
        "h.language": "Language of form and report.",
        # presets (2026-11-21): slots with all settings, for every model ({n}: PRESET_SLOTS, 10 since 2026-11-23)
        "s.presets": "Favorites", "f.preset": "Favorite", "v.empty": "(Empty)",
        "h.preset": "←→  slot 1-{n}   Enter: Load it   S: Save settings / Change name.",
        "n.loaded": "Favorite {n} \"{name}\" loaded.", "n.saved": "Saved in favorite {n} \"{name}\".",
        "n.empty": "Favorite {n} is empty: S saves the settings below in it.",
        "n.kept": "Not available here, kept as it was: {what}.", "n.not_saved": "Could not save the favorite.",
        "ps.title": "Save the settings in favorite {n}", "ps.name": "Name: ",
        "help.name": "Type a name   Enter Save   Esc Cancel",
        # run
        "run.making": "Making the project...", "run.done": "Press any key to close this window.",
        "run.error": "Not made: {msg}", "run.back": "Press any key to go back to the form.",
        "run.cancelled": "Canceled. Nothing was made or saved.",
        "run.windows_only": "The form needs the Windows console. Use the options instead (orientr --help).",
        "run.legacy_console": "This console window runs in legacy mode, which cannot show the form. Right-click its "
                              "title bar > Properties, untick \"Use legacy console\", open a new window and type "
                              "orientr again. Or use Windows Terminal.",
        "run.no_parts": "Choose at least one part to print.",
        "run.no_models": "No SOMA model found on this PC. Build a model in SOMA first.",
        "run.opened": "Orientr opened in its own window.",
        # preview
        "b.preview": "Analyze",
        "h.preview": "Quick report of Bambu Studio's view of your project: warnings, plates, print time, filament and "
                     "cost.",
        "h.make": "Makes the Bambu Studio project (.3mf) and saves these choices for next time.",
        "pv.title": "Analyze", "pv.plates": "Plates", "pv.time": "Print time", "pv.filament": "Filament", "pv.cost": "Cost",
        "pv.plate": "Plate {n}", "pv.parts": "{n} parts", "pv.part": "1 part", "pv.warn": "⚠  Plate {n}: {msg}", "pv.part_warn": "⚠  {msg}",
        "pv.slicing": "Bambu Studio is slicing the project... {s} s   (Esc stops)",
        "pv.preparing": "Preparing the parts... {s} s   (Esc stops)", "pv.stopping": "Stopping... {s} s",
        "pv.nowarn": "No warnings from the Bambu Studio slice",
        "pv.note": "Bambu Studio's estimate for the choices in the form. Nothing was saved.",
        "pv.back": "Press any key to go back to the form.", "pv.stopped": "Analysis stopped.",
        "pv.back_scroll": "↑↓  Scroll   Any other key: Back to the form.",
        # status line
        "s.ok": "Bambu Studio {v}: Up to date",
        "s.ok_unknown": "Bambu Studio installed (version unknown)",
        "s.update": "Update Bambu Studio ({v} available)",
        "s.untested": "Bambu Studio {v} untested: orientr --selftest",
        "s.old_template": "Template from an older Bambu Studio: Save it again",
        "s.missing": "Bambu Studio not found: Set BAMBU_STUDIO",
        "s.orientr_ok": "Orientr {v}: Up to date",
        "s.orientr_new": "Update Orientr ({new} available, you have {v})",
        "s.orientr_local": "Orientr {v}",
    },
    "de": {
        "f.printer": "Drucker", "f.filament": "Filament", "f.process": "Prozess", "f.walls": "Wände",
        "f.infill": "Füllung", "f.support": "Stützen", "f.brim": "Umrandung", "f.parts": "Teile", "f.parts_n": "Teile ({n})",
        "f.open": "In Bambu Studio öffnen", "f.language": "Sprache",
        "f.nozzle": "Düse", "f.nozzle_size": "Düsengröße",
        "s.printer": "Druckereinstellungen", "s.quality": "Qualitätseinstellungen",
        "s.volume": "Mengeneinstellungen", "s.other": "Sonstige",
        "v.left": "Nur links", "v.right": "Nur rechts", "v.na": "k. A.",
        "v.profile": "Wie im Profil", "v.wall": "{n} Wand", "v.walls": "{n} Wände", "v.auto": "Auto (pro Teil)",
        "v.on": "Immer", "v.off": "Nie", "v.yes": "Ja", "v.no": "Nein", "v.parts": "{on} von {all}",
        "v.current": "Aktuell",
        "b.make": "Generieren", "b.cancel": "Abbrechen",
        "help.form": "↑↓  Feld   ←→  Ändern   Enter Liste/Knopf   G A B  Knöpfe   Esc Abbrechen",
        "keys.buttons": "GAB",
        "help.list": "↑↓  Wählen   A-Z Springen   Bild ↑/↓  Seite   Enter Übernehmen   Esc Zurück",
        "help.models": "↑↓  Wählen   Bild ↑/↓  Seite   Enter Öffnen   Esc Abbrechen",
        "pick.model": "Modell wählen (neuestes zuerst)",
        "h.printer": "{n} Drucker mit Vorlage.",
        "h.filament": "{n} Profile für diesen Drucker. Enter: ganze Liste.",
        "h.process": "Profil für Schichthöhe und Tempo.",
        "h.walls": "Oder eine Zahl von 1 bis 20 eingeben. Kleine und Schnapp-/Lastteile bekommen ohnehin 4+ Wände.",
        "h.infill": "Oder einen Prozentwert von 0 bis 100 eingeben. Kleine und Schnapp-/Lastteile bekommen ohnehin mehr "
                    "Füllung.",
        "h.support": "Auto: Pro Teil, nach seinen Überhängen.",
        "h.brim": "Auto: Pro Teil (hoch, klein oder verzugsanfällig).",
        "h.parts": "Enter: Gedruckte Teile wählen, mit ←→  wie viele von jedem.",
        "f.duplicates": "Duplikate", "f.max_plates": "Max. Druckplatten",
        "v.no_limit": "Ohne Grenze", "v.plate": "1 Druckplatte", "v.plates": "{n} Druckplatten",
        "h.duplicates": "Der ganze Satz so oft (pro Teil: unter Teile). Enter, oder eine Zahl eingeben.",
        "h.max_plates": "Mehr Druckplatten nötig: Die Teile werden enger gelegt; passen sie dann nicht, wird nichts erstellt.",
        "h.nozzle_size": "Größen, die dieser Drucker unterstützt.",
        "h.nozzle": "Zwei-Düsen-Drucker: Auto oder eine Düse erzwingen.",
        "h.open": "Öffnet das Projekt in Bambu Studio.",
        "f.prestart": "Bambu Studio im Hintergrund",
        "h.prestart": "Bambu Studio verborgen: Öffnen geht schneller. Ändern, dann Enter: Jetzt starten/schließen. "
                      "⚠ Belastet den PC; beim Start ist sein Banner einige Sekunden sichtbar.",
        "bg.opening": "Startet…", "bg.open": "Offen", "bg.closing": "Schließt…", "bg.closed": "Geschlossen",
        "n.prestart_on": "Enter: Bambu Studio jetzt im Hintergrund starten.",
        "n.prestart_off": "Enter: Bambu Studio im Hintergrund jetzt schließen.",
        "n.prestart_started": "Gespeichert. Bambu Studio startet im Hintergrund, sobald der PC ruhig ist.",
        "n.prestart_not_started": "Gespeichert. Bambu Studio wurde jetzt nicht im Hintergrund gestartet (schon "
                                  "offen, oder In Bambu Studio öffnen ist aus).",
        "n.prestart_first": "Gespeichert. Bambu Studio kann noch nicht im Hintergrund starten: zuerst einmal selbst "
                            "öffnen.",
        "n.prestart_closed": "Gespeichert. Bambu Studio im Hintergrund wird geschlossen (ein benutztes bleibt offen).",
        "h.language": "Sprache von Formular und Bericht.",
        "s.presets": "Favoriten", "f.preset": "Favorit", "v.empty": "(Leer)",
        "h.preset": "←→  Platz 1-{n}   Enter: Laden   S: Einstellungen speichern / Namen ändern.",
        "n.loaded": "Favorit {n} \"{name}\" geladen.", "n.saved": "In Favorit {n} \"{name}\" gespeichert.",
        "n.empty": "Favorit {n} ist leer: S speichert die Einstellungen darunter darin.",
        "n.kept": "Hier nicht verfügbar, unverändert: {what}.",
        "n.not_saved": "Der Favorit konnte nicht gespeichert werden.",
        "ps.title": "Einstellungen in Favorit {n} speichern", "ps.name": "Name: ",
        "help.name": "Namen eingeben   Enter Speichern   Esc Abbrechen",
        "run.making": "Projekt wird erstellt...", "run.done": "Eine Taste drücken, um das Fenster zu "
                                                             "schließen.",
        "run.error": "Nicht erstellt: {msg}", "run.back": "Eine Taste drücken, um zum Formular zurückzukehren.",
        "run.cancelled": "Abgebrochen. Es wurde nichts erstellt oder gespeichert.",
        "run.windows_only": "Das Formular braucht die Windows-Konsole. Nutzen Sie stattdessen die Optionen "
                            "(orientr --help).",
        "run.legacy_console": "Dieses Konsolenfenster läuft im Legacymodus und kann das Formular nicht zeigen. "
                              "Rechtsklick auf die Titelleiste > Eigenschaften, \"Legacykonsole verwenden\" "
                              "abwählen, ein neues Fenster öffnen und erneut orientr eingeben. Oder Windows Terminal "
                              "nutzen.",
        "run.no_parts": "Wählen Sie mindestens ein Teil zum Drucken.",
        "run.no_models": "Kein SOMA-Modell auf diesem PC gefunden. Erstellen Sie zuerst ein Modell in SOMA.",
        "run.opened": "Orientr wurde in einem eigenen Fenster geöffnet.",
        "b.preview": "Analysieren",
        "h.preview": "Kurzbericht aus Bambu Studio: Warnungen, Druckplatten, Druckzeit, Filamentverbrauch und Kosten.",
        "h.make": "Erstellt das Bambu-Studio-Projekt (.3mf) und speichert diese Auswahl für das nächste Mal.",
        "pv.title": "Analysieren", "pv.plates": "Druckplatten", "pv.time": "Druckzeit", "pv.filament": "Filament", "pv.cost": "Kosten",
        "pv.plate": "Druckplatte {n}", "pv.parts": "{n} Teile", "pv.part": "1 Teil", "pv.warn": "⚠  Druckplatte {n}: {msg}", "pv.part_warn": "⚠  {msg}",
        "pv.slicing": "Bambu Studio slicet das Projekt... {s} s   (Esc bricht ab)",
        "pv.preparing": "Teile werden vorbereitet... {s} s   (Esc bricht ab)", "pv.stopping": "Wird abgebrochen... {s} s",
        "pv.nowarn": "Keine Warnungen vom Slicen in Bambu Studio",
        "pv.note": "Schätzung von Bambu Studio für die Einstellungen im Formular. Es wurde nichts gespeichert.",
        "pv.back": "Eine Taste drücken, um zum Formular zurückzukehren.", "pv.stopped": "Analyse abgebrochen.",
        "pv.back_scroll": "↑↓  Blättern   Andere Taste: Zurück zum Formular.",
        "s.ok": "Bambu Studio {v}: Aktuell",
        "s.ok_unknown": "Bambu Studio installiert (Version unbekannt)",
        "s.update": "Bambu Studio aktualisieren ({v} verfügbar)",
        "s.untested": "Bambu Studio {v} ungetestet: orientr --selftest",
        "s.old_template": "Vorlage aus älterem Bambu Studio: Neu speichern",
        "s.missing": "Bambu Studio nicht gefunden: BAMBU_STUDIO setzen",
        "s.orientr_ok": "Orientr {v}: Aktuell",
        "s.orientr_new": "Orientr aktualisieren ({new} verfügbar, Sie haben {v})",
        "s.orientr_local": "Orientr {v}",
    },
    "fr": {
        "f.printer": "Imprimante", "f.filament": "Filament", "f.process": "Processus", "f.walls": "Parois",
        "f.infill": "Remplissage", "f.support": "Supports", "f.brim": "Bordure", "f.parts": "Pièces", "f.parts_n": "Pièces ({n})",
        "f.open": "Ouvrir dans Bambu Studio", "f.language": "Langue",
        "f.nozzle": "Buse", "f.nozzle_size": "Taille de buse",
        "s.printer": "Réglages de l'imprimante", "s.quality": "Réglages de qualité",
        "s.volume": "Réglages de quantité", "s.other": "Autre",
        "v.left": "Gauche uniquement", "v.right": "Droite uniquement", "v.na": "N/D",
        "v.profile": "Comme le préréglage", "v.wall": "{n} paroi", "v.walls": "{n} parois", "v.auto": "Auto (par pièce)",
        "v.on": "Toujours", "v.off": "Jamais", "v.yes": "Oui", "v.no": "Non", "v.parts": "{on} sur {all}",
        "v.current": "Actuel",
        "b.make": "Générer", "b.cancel": "Annuler",
        "help.form": "↑↓  Champ   ←→  Changer   Entrée Choisir   G A N  Boutons   Échap Annuler",
        "keys.buttons": "GAN",
        "help.list": "↑↓  Choisir   A-Z Saut   Pg.préc/Pg.suiv Page   Entrée Valider   Échap Retour",
        "help.models": "↑↓  Choisir   Pg.préc/Pg.suiv Page   Entrée Ouvrir   Échap Annuler",
        "pick.model": "Choisissez un modèle SOMA (le plus récent d'abord)",
        "h.printer": "{n} imprimantes avec un modèle.",
        "h.filament": "{n} préréglages pour cette imprimante. Entrée : Liste.",
        "h.process": "Préréglage de hauteur de couche et vitesse.",
        "h.walls": "Ou taper un nombre de 1 à 20. Petites pièces et pièces à clipser ou porteuses : De toute façon 4+ "
                   "parois.",
        "h.infill": "Ou taper un pourcentage de 0 à 100. Petites pièces et pièces à clipser ou porteuses : De toute "
                    "façon plus de remplissage.",
        "h.support": "Auto : Par pièce, selon ses porte-à-faux.",
        "h.brim": "Auto : Par pièce (haute, petite ou sujette au gauchissement).",
        "h.parts": "Entrée : Choisir les pièces à imprimer, et avec ←→  combien de chacune.",
        "f.duplicates": "Duplicata", "f.max_plates": "Plaques max.",
        "v.no_limit": "Sans limite", "v.plate": "1 plaque", "v.plates": "{n} plaques",
        "h.duplicates": "Tout le jeu autant de fois (par pièce : dans Pièces). Entrée, ou taper un nombre.",
        "h.max_plates": "Plus de plaques nécessaires : Les pièces sont rapprochées ; si cela ne suffit pas, rien n'est créé.",
        "h.nozzle_size": "Tailles gérées par cette imprimante.",
        "h.nozzle": "Deux buses : Auto, ou forcer une buse.",
        "h.open": "Ouvre le projet dans Bambu Studio.",
        "f.prestart": "Bambu Studio en arrière-plan",
        "h.prestart": "Bambu Studio masqué : Ouverture plus rapide. Changer, puis Entrée : Démarrer/fermer maintenant. "
                      "⚠ Sollicite le PC ; au démarrage, sa bannière s'affiche quelques secondes.",
        "bg.opening": "Ouverture…", "bg.open": "Ouvert", "bg.closing": "Fermeture…", "bg.closed": "Fermé",
        "n.prestart_on": "Entrée : Démarrer Bambu Studio en arrière-plan maintenant.",
        "n.prestart_off": "Entrée : Fermer Bambu Studio en arrière-plan maintenant.",
        "n.prestart_started": "Enregistré. Bambu Studio démarre en arrière-plan dès que le PC est calme.",
        "n.prestart_not_started": "Enregistré. Bambu Studio n'a pas démarré en arrière-plan (déjà ouvert, ou "
                                  "Ouvrir dans Bambu Studio est désactivé).",
        "n.prestart_first": "Enregistré. Bambu Studio ne peut pas encore démarrer en arrière-plan : ouvrez-le d'abord "
                            "une fois vous-même.",
        "n.prestart_closed": "Enregistré. Bambu Studio en arrière-plan se ferme (celui que vous utilisez reste ouvert).",
        "h.language": "Langue du formulaire et du rapport.",
        "s.presets": "Favoris", "f.preset": "Favori", "v.empty": "(Vide)",
        "h.preset": "←→  emplacement 1-{n}   Entrée : Charger   S : Enregistrer les réglages / Changer le nom.",
        "n.loaded": "Favori {n} « {name} » chargé.", "n.saved": "Enregistré dans le favori {n} « {name} ».",
        "n.empty": "Le favori {n} est vide : S y enregistre les réglages ci-dessous.",
        "n.kept": "Indisponible ici, inchangé : {what}.", "n.not_saved": "Le favori n'a pas pu être enregistré.",
        "ps.title": "Enregistrer les réglages dans le favori {n}", "ps.name": "Nom : ",
        "help.name": "Tapez un nom   Entrée Enregistrer   Échap Annuler",
        "run.making": "Création du projet...", "run.done": "Appuyez sur une touche pour fermer cette "
                                                           "fenêtre.",
        "run.error": "Non créé : {msg}", "run.back": "Appuyez sur une touche pour revenir au formulaire.",
        "run.cancelled": "Annulé. Rien n'a été créé ni enregistré.",
        "run.windows_only": "Le formulaire a besoin de la console Windows. Utilisez plutôt les options "
                            "(orientr --help).",
        "run.legacy_console": "Cette fenêtre de console est en mode hérité et ne peut pas afficher le formulaire. "
                              "Clic droit sur sa barre de titre > Propriétés, décochez « Utiliser la console "
                              "héritée », ouvrez une nouvelle fenêtre et tapez à nouveau orientr. Ou utilisez Windows "
                              "Terminal.",
        "run.no_parts": "Choisissez au moins une pièce à imprimer.",
        "run.no_models": "Aucun modèle SOMA trouvé sur ce PC. Créez d'abord un modèle dans SOMA.",
        "run.opened": "Orientr s'est ouvert dans sa propre fenêtre.",
        "b.preview": "Analyser",
        "h.preview": "Rapport rapide de Bambu Studio : Avertissements, plaques, durée, filament utilisé et coût.",
        "h.make": "Crée le projet Bambu Studio (.3mf) et enregistre ces choix pour la prochaine fois.",
        "pv.title": "Analyser", "pv.plates": "Plaques", "pv.time": "Durée", "pv.filament": "Filament", "pv.cost": "Coût",
        "pv.plate": "Plaque {n}", "pv.parts": "{n} pièces", "pv.part": "1 pièce", "pv.warn": "⚠  Plaque {n} : {msg}",
        "pv.part_warn": "⚠  {msg}",
        "pv.slicing": "Bambu Studio découpe le projet... {s} s   (Échap arrête)",
        "pv.preparing": "Préparation des pièces... {s} s   (Échap arrête)", "pv.stopping": "Arrêt... {s} s",
        "pv.nowarn": "Aucun avertissement du découpage de Bambu Studio",
        "pv.note": "Estimation de Bambu Studio pour les choix du formulaire. Rien n'a été enregistré.",
        "pv.back": "Appuyez sur une touche pour revenir au formulaire.", "pv.stopped": "Analyse arrêtée.",
        "pv.back_scroll": "↑↓  Défiler   Autre touche : Retour au formulaire.",
        "s.ok": "Bambu Studio {v} : À jour",
        "s.ok_unknown": "Bambu Studio installé (version inconnue)",
        "s.update": "Mettre à jour Bambu Studio ({v} disponible)",
        "s.untested": "Bambu Studio {v} non testé : orientr --selftest",
        "s.old_template": "Modèle d'un ancien Bambu Studio : Réenregistrez-le",
        "s.missing": "Bambu Studio introuvable : Définissez BAMBU_STUDIO",
        "s.orientr_ok": "Orientr {v} : À jour",
        "s.orientr_new": "Mettre à jour Orientr ({new} disponible, vous avez {v})",
        "s.orientr_local": "Orientr {v}",
    },
}

# --- the report, its reasons and warnings, and the check (Bambu Studio's own messages stay in its English) ----------
REPORT: dict[str, dict[str, str]] = {
    "en": {
        "msg.saved": "Choices saved in {path}",
        "rp.title": "# Print settings: {title}",
        "rp.made": "Made by Orientr on {time}. Open `{file}` in Bambu Studio, check, slice, send.",
        "rp.printer": "- Printer: {printer} (usable bed {x} x {y} x {z} mm{only})",
        "rp.only": ", {nozzle} only: filament fixed to it",
        "nz.1": "left nozzle", "nz.2": "right nozzle",
        "rp.process": "- Process: {process}", "rp.filaments": "- Filament(s): {filaments}",
        "rp.chosen": " (chosen: {what})",
        "rp.template": "- Template: {path} (saved with {app})",
        "rp.wide": "- Project-wide: layer {layer} mm, walls {walls}, infill {infill}, support {support}, brim {brim}",
        "rp.notice": "> **Template:** {text}",
        "rp.plate": "## Plate {n}",
        "rp.nested": "- In the opening of **{host}**: {parts}",
        "rp.head": "| Part | Orientation | Size (mm) | Brim | Support | Why |",
        "rp.with": " + {name} (filament {n})", "rp.tree": "tree", "rp.none": "off",
        "rp.volume": "- Quantity: {n} {n:object|objects} on {plates} {plates:plate|plates} (duplicates × {dup}, max plates {max})",
        "rp.check": "## Check in Bambu Studio",
        "o.modelled": "as modeled", "o.axis": "{axis} down", "o.face": "face {vec} down", "o.up": "{key} up (bambu.json)",
        "r.sup_on_json": "support on (bambu.json)", "r.sup_off_json": "support off (bambu.json)",
        "r.sup_on_all": "support on for every part (chosen)", "r.sup_off_all": "support off for every part (chosen)",
        "r.sup_on": "support on: {n} {n:overhang region|overhang regions}, {area} mm², largest {big} mm² (flatter than {slope}° from "
                    "horizontal)",
        "r.islands": ", {n} {n:island|islands} with nothing below",
        "r.rim": "; bottom edge ignored (reaches {mm} mm past the first layer)",
        "r.sup_off": "support off: {why}", "r.overhang": "{area} mm² overhang", "r.no_overhang": "no overhang",
        "r.ignored": " (ignored: {list})",
        "i.spots": "{n} {n:spot|spots}", "i.ledges": "{n} {n:ledge|ledges}", "i.bridges": "{n} {n:bridge|bridges}", "i.bed rims": "{n} {n:bed rim|bed rims}",
        "r.rests": "center of mass {mm} mm past the bed contact: that side rests on the support",
        "r.brim_json": "brim {mm} mm (bambu.json)", "r.no_brim_json": "no brim (bambu.json)",
        "r.no_brim_all": "no brim for any part (chosen)",
        "b.lever_rest": "contact {w} mm wide, {o} mm past it", "b.lever": "{m} mm from the contact edge",
        "b.tall": "tall and narrow: center of mass {h} mm high, {lever} (ratio {r})",
        "b.tips": "center of mass on or outside the contact edge: tips over",
        "b.small_contact": "small bed contact {a} mm²",
        "b.warp_long": "{warp}, footprint {l} mm long",
        "b.warp_small": "{warp}, small part ({a} mm² on the bed, {l} mm long): comes loose easily",
        "b.all": "brim on every part (chosen)",
        "r.brim": "brim {mm} mm: {why}", "r.no_brim": "no brim: {a} mm² on the bed, stable (ratio {r})",
        "wp.chamber": "{typ} {i} wants a heated chamber ({c} °C)", "wp.bed": "{typ} {i} wants a heated bed ({c} °C)",
        "wp.warps": "{typ} {i} warps", "wp.filament": "filament",
        "r.function": "{fn} part (bambu.json)", "r.small": "small part ({s} mm, {v} cm³): 4 walls, nearly solid",
        "r.walls_json": "{n} walls (bambu.json)", "r.infill_json": "infill {v} (bambu.json)",
        "r.rectilinear": "rectilinear infill (needed for 100 %)", "r.setting_json": "{k} = {v} (bambu.json)",
        "r.strength": "strength: {note}, {deg}° out of the layers",
        "ld.along": "load along {spec} (bambu.json)", "ld.longest": "load along its longest side ({axis}, {mm} mm)",
        "w.load": "the load runs {deg}° across the layers (the weak direction): {advice}",
        "w.load_up": "choose an \"up\" in bambu.json that lays the load axis flat",
        "w.load_none": "none of the tested orientations that fit lays it flat; check \"load_axis\" or set an \"up\" "
                       "in bambu.json, or turn the part in Bambu Studio",
        "w.sup_off": "support is off (chosen), but {area} mm² overhang needs it",
        "w.brim_off": "brim is off (chosen), but this part is tall/narrow or has little bed contact",
        "w.fit": "does not fit the printer ({x} x {y} x {z} mm{brim}; usable {ux} x {uy} x {uz})",
        "w.fit_brim": " + {mm} mm brim",
        "w.steep": "{a} mm² steeper than {deg}° from vertical (SOMA's design rule) without support: check the preview",
        "w.no_contact": "almost no contact with the bed: the part rests on an edge or a point",
        "w.tips_far": "the center of mass lies outside the contact area too far for the support to carry: the part "
                      "tips over, choose another orientation (\"up\" in bambu.json)",
        "w.tips": "the center of mass lies outside the contact area and there is no support: the part tips over, "
                  "choose another orientation (\"up\" in bambu.json)",
        "w.tower": "stands on the prime tower's spot (no other room on the plate): in Bambu Studio move the prime "
                   "tower to a free spot before slicing",
        "w.no_spot": "no free spot on the plate (too large, or blocked by the printer's no-go zones)",
        "w.filament": "wants filament {n}, the template has {have}: printed with filament 1. Add filament {n} in "
                      "Bambu Studio and assign it to this part",
        "w.lift": "a merged part reaches below this part's bottom: it lifts the part off the bed",
        "c.skipped": "check skipped: Bambu Studio not found at {path} (set BAMBU_STUDIO)",
        "c.failed": "Bambu Studio could not slice the project: {err} (code {code})",
        "c.warns": "Bambu Studio warns (plate {n}): {msg}",
        "c.rim": "{name}: most likely its rounded or chamfered bottom edge, which reaches {mm} mm past the first "
                 "layer. That prints fine without support; Bambu Studio cannot put support that low and warns about it",
        "c.sliced_warn": "Bambu Studio sliced {n:the plate|all {n} plates} with the warnings below ({s} s)",
        "c.sliced_ok": "Bambu Studio sliced {n:the plate|all {n} plates} without errors or warnings ({s} s)",
        "c.pictures": "{n:plate picture|plate pictures}: {first}{n:| ... plate{n}.png}",
        "c.settings_ok": "all per-part settings of {n} {n:part|parts} survived loading in Bambu Studio",
        "c.missing": "{name}: missing after loading", "c.diff": "{name}: {list}",
        "c.plates": "Bambu Studio sees {g} {g:plate|plates}, Orientr wrote {n}",
        "c.gcode": "only {g} of {n} {n:plate|plates} produced G-code (empty plate?)",
        "ta.old": "The template was saved with Bambu Studio {saved}; the installed version is {inst}: Bambu may have "
                  "updated its printer and filament presets since. Open {file} in Bambu Studio, check printer, "
                  "filament and process, and save it again",
        "e.filament": "the filament {name!r} has no Bambu Studio preset for the {printer}; for example: {examples}",
        "e.printer": "unknown printer {name!r}; Bambu Studio knows: {names}",
        "e.nozzle_size": "a {size} mm nozzle does not fit the {printer}; choose from: {sizes}",
        "e.no_template": "no template for the {printer} yet. Make it once in the Bambu Studio window (not its "
                         "command line):\n  1. Open Bambu Studio, choose the {printer} with the 0.4 nozzle (any "
                         "filament and process).\n  2. Put any small object on the plate.\n  3. File > Save Project "
                         "As > {folder} (any name).\nThen run this again.",
        "e.no_parts": "nothing to print: every part is skipped (or merged into a skipped part)",
        "e.max_plates": "{n} objects need {need} plates, more than the maximum of {max}: lower Duplicates or a "
                        "part's copies, or raise Max plates",
        "e.no_build": "no build found: run `soma build` first",
    },
    "de": {
        "msg.saved": "Auswahl gespeichert in {path}",
        "rp.title": "# Druckeinstellungen: {title}",
        "rp.made": "Erstellt von Orientr am {time}. `{file}` in Bambu Studio öffnen, prüfen, slicen, senden.",
        "rp.printer": "- Drucker: {printer} (nutzbares Druckbett {x} x {y} x {z} mm{only})",
        "rp.only": ", nur {nozzle}: Filament fest zugeordnet",
        "nz.1": "linke Düse", "nz.2": "rechte Düse",
        "rp.process": "- Prozess: {process}", "rp.filaments": "- Filament(e): {filaments}",
        "rp.chosen": " (gewählt: {what})",
        "rp.template": "- Vorlage: {path} (gespeichert mit {app})",
        "rp.wide": "- Für das ganze Projekt: Schicht {layer} mm, Wände {walls}, Füllung {infill}, Stützen {support}, "
                   "Umrandung {brim}",
        "rp.notice": "> **Vorlage:** {text}",
        "rp.plate": "## Druckplatte {n}",
        "rp.nested": "- In der Öffnung von **{host}**: {parts}",
        "rp.head": "| Teil | Ausrichtung | Größe (mm) | Umrandung | Stützen | Warum |",
        "rp.with": " + {name} (Filament {n})", "rp.tree": "Baum", "rp.none": "aus",
        "rp.volume": "- Menge: {n} Objekte auf {plates} {plates:Druckplatte|Druckplatten} (Duplikate × {dup}, max. "
                     "Druckplatten {max})",
        "rp.check": "## Prüfung in Bambu Studio",
        "o.modelled": "wie modelliert", "o.axis": "{axis} unten", "o.face": "Fläche {vec} unten",
        "o.up": "{key} oben (bambu.json)",
        "r.sup_on_json": "Stützen an (bambu.json)", "r.sup_off_json": "Stützen aus (bambu.json)",
        "r.sup_on_all": "Stützen an für alle Teile (gewählt)", "r.sup_off_all": "Stützen aus für alle Teile (gewählt)",
        "r.sup_on": "Stützen an: {n} {n:Überhangbereich|Überhangbereiche}, {area} mm², größter {big} mm² (flacher als {slope}° zur "
                    "Waagrechten)",
        "r.islands": ", {n} {n:Insel|Inseln} ohne etwas darunter",
        "r.rim": "; Unterkante ignoriert (ragt {mm} mm über die erste Schicht hinaus)",
        "r.sup_off": "Stützen aus: {why}", "r.overhang": "{area} mm² Überhang", "r.no_overhang": "kein Überhang",
        "r.ignored": " (ignoriert: {list})",
        "i.spots": "{n} {n:Stelle|Stellen}", "i.ledges": "{n} {n:Kante|Kanten}", "i.bridges": "{n} {n:Brücke|Brücken}", "i.bed rims": "{n} {n:Druckbettkante|Druckbettkanten}",
        "r.rests": "Schwerpunkt {mm} mm außerhalb der Auflage auf dem Druckbett: diese Seite ruht auf den Stützen",
        "r.brim_json": "Umrandung {mm} mm (bambu.json)", "r.no_brim_json": "keine Umrandung (bambu.json)",
        "r.no_brim_all": "für kein Teil eine Umrandung (gewählt)",
        "b.lever_rest": "Auflage {w} mm breit, {o} mm darüber hinaus", "b.lever": "{m} mm vom Rand der Auflage",
        "b.tall": "hoch und schmal: Schwerpunkt {h} mm hoch, {lever} (Verhältnis {r})",
        "b.tips": "Schwerpunkt auf oder außerhalb des Auflagerands: kippt um",
        "b.small_contact": "kleine Auflage auf dem Druckbett {a} mm²",
        "b.warp_long": "{warp}, Grundfläche {l} mm lang",
        "b.warp_small": "{warp}, kleines Teil ({a} mm² auf dem Druckbett, {l} mm lang): löst sich leicht",
        "b.all": "Umrandung an allen Teilen (gewählt)",
        "r.brim": "Umrandung {mm} mm: {why}", "r.no_brim": "keine Umrandung: {a} mm² auf dem Druckbett, stabil (Verhältnis {r})",
        "wp.chamber": "{typ} {i} braucht eine beheizte Kammer ({c} °C)",
        "wp.bed": "{typ} {i} braucht ein beheiztes Druckbett ({c} °C)", "wp.warps": "{typ} {i} verzieht sich",
        "wp.filament": "Filament",
        "r.function": "{fn}-Teil (bambu.json)", "r.small": "kleines Teil ({s} mm, {v} cm³): 4 Wände, fast massiv",
        "r.walls_json": "{n} Wände (bambu.json)", "r.infill_json": "Füllung {v} (bambu.json)",
        "r.rectilinear": "geradlinige Füllung (nötig für 100 %)", "r.setting_json": "{k} = {v} (bambu.json)",
        "r.strength": "Festigkeit: {note}, {deg}° aus den Schichten",
        "ld.along": "Last entlang {spec} (bambu.json)", "ld.longest": "Last entlang der längsten Seite ({axis}, {mm} mm)",
        "w.load": "die Last läuft {deg}° quer zu den Schichten (die schwache Richtung): {advice}",
        "w.load_up": "ein \"up\" in bambu.json wählen, das die Lastachse flach legt",
        "w.load_none": "keine der getesteten passenden Ausrichtungen legt sie flach; \"load_axis\" prüfen oder ein "
                       "\"up\" in bambu.json setzen, oder das Teil in Bambu Studio drehen",
        "w.sup_off": "Stützen sind aus (gewählt), aber {area} mm² Überhang braucht sie",
        "w.brim_off": "Umrandung ist aus (gewählt), aber dieses Teil ist hoch/schmal oder hat wenig Auflage auf dem "
                      "Druckbett",
        "w.fit": "passt nicht auf den Drucker ({x} x {y} x {z} mm{brim}; nutzbar {ux} x {uy} x {uz})",
        "w.fit_brim": " + {mm} mm Umrandung",
        "w.steep": "{a} mm² steiler als {deg}° zur Senkrechten (SOMA-Konstruktionsregel) ohne Stützen: Vorschau prüfen",
        "w.no_contact": "fast keine Auflage auf dem Druckbett: das Teil steht auf einer Kante oder einem Punkt",
        "w.tips_far": "der Schwerpunkt liegt zu weit außerhalb der Auflage, als dass die Stützen ihn tragen: das Teil "
                      "kippt, andere Ausrichtung wählen (\"up\" in bambu.json)",
        "w.tips": "der Schwerpunkt liegt außerhalb der Auflage und es gibt keine Stützen: das Teil kippt, andere "
                  "Ausrichtung wählen (\"up\" in bambu.json)",
        "w.tower": "steht auf dem Platz des Reinigungsturms (sonst kein Platz auf der Druckplatte): in Bambu Studio den "
                   "Reinigungsturm vor dem Slicen an eine freie Stelle schieben",
        "w.no_spot": "kein freier Platz auf der Druckplatte (zu groß, oder von Sperrzonen des Druckers blockiert)",
        "w.filament": "braucht Filament {n}, die Vorlage hat {have}: mit Filament 1 gedruckt. Filament {n} in Bambu "
                      "Studio hinzufügen und diesem Teil zuweisen",
        "w.lift": "ein eingefügtes Teil reicht unter den Boden dieses Teils: es hebt das Teil vom Druckbett",
        "c.skipped": "Prüfung übersprungen: Bambu Studio nicht gefunden unter {path} (BAMBU_STUDIO setzen)",
        "c.failed": "Bambu Studio konnte das Projekt nicht slicen: {err} (Code {code})",
        "c.warns": "Bambu Studio warnt (Druckplatte {n}): {msg}",
        "c.rim": "{name}: wahrscheinlich die abgerundete oder abgeschrägte Unterkante, die {mm} mm über die erste "
                 "Schicht hinausragt. Das druckt ohne Stützen gut; so tief kann Bambu Studio keine Stützen setzen und "
                 "warnt deshalb",
        "c.sliced_warn": "Bambu Studio hat {n:die Druckplatte|alle {n} Druckplatten} gesliced, mit den Warnungen unten ({s} s)",
        "c.sliced_ok": "Bambu Studio hat {n:die Druckplatte|alle {n} Druckplatten} ohne Fehler oder Warnungen gesliced ({s} "
                       "s)",
        "c.pictures": "{n:Druckplattenbild|Druckplattenbilder}: {first}{n:| ... plate{n}.png}",
        "c.settings_ok": "alle Einstellungen pro Teil ({n} {n:Teil|Teile}) blieben beim Laden in Bambu Studio erhalten",
        "c.missing": "{name}: fehlt nach dem Laden", "c.diff": "{name}: {list}",
        "c.plates": "Bambu Studio sieht {g} {g:Druckplatte|Druckplatten}, Orientr schrieb {n}",
        "c.gcode": "nur {g} von {n} {n:Druckplatte|Druckplatten} ergaben G-Code (leere Druckplatte?)",
        "ta.old": "Die Vorlage wurde mit Bambu Studio {saved} gespeichert, installiert ist {inst}: Bambu hat "
                  "seitdem vielleicht seine Drucker- und Filamentprofile geändert. {file} in Bambu Studio öffnen, "
                  "Drucker, Filament und Prozess prüfen und neu speichern",
        "e.filament": "das Filament {name!r} hat kein Bambu-Studio-Profil für den {printer}; zum Beispiel: {examples}",
        "e.printer": "unbekannter Drucker {name!r}; Bambu Studio kennt: {names}",
        "e.nozzle_size": "eine {size}-mm-Düse passt nicht zum {printer}; wählen Sie aus: {sizes}",
        "e.no_template": "noch keine Vorlage für den {printer}. Einmal im Bambu-Studio-Fenster erstellen (nicht über die "
                         "Befehlszeile):\n  1. Bambu Studio öffnen, den {printer} mit 0,4-Düse wählen (beliebiges Filament und "
                         "beliebiger Prozess).\n  2. Ein kleines Objekt auf die Druckplatte legen.\n  3. Datei > Projekt "
                         "speichern unter > {folder} (beliebiger Name).\nDann erneut starten.",
        "e.no_parts": "nichts zu drucken: alle Teile sind ausgeschlossen (oder in ein ausgeschlossenes Teil eingefügt)",
        "e.max_plates": "{n} Objekte brauchen {need} Druckplatten, mehr als das Maximum von {max}: weniger Duplikate oder "
                        "Kopien eines Teils, oder Max. Druckplatten erhöhen",
        "e.no_build": "kein Build gefunden: zuerst `soma build` ausführen",
    },
    "fr": {
        "msg.saved": "Choix enregistrés dans {path}",
        "rp.title": "# Réglages d'impression : {title}",
        "rp.made": "Créé par Orientr le {time}. Ouvrez `{file}` dans Bambu Studio, vérifiez, découpez, "
                   "envoyez.",
        "rp.printer": "- Imprimante : {printer} (plateau utile {x} x {y} x {z} mm{only})",
        "rp.only": ", {nozzle} uniquement : filament affecté à celle-ci",
        "nz.1": "buse gauche", "nz.2": "buse droite",
        "rp.process": "- Processus : {process}", "rp.filaments": "- Filament(s) : {filaments}",
        "rp.chosen": " (choisi : {what})",
        "rp.template": "- Modèle : {path} (enregistré avec {app})",
        "rp.wide": "- Pour tout le projet : couche {layer} mm, parois {walls}, remplissage {infill}, supports "
                   "{support}, bordure {brim}",
        "rp.notice": "> **Modèle :** {text}",
        "rp.plate": "## Plaque {n}",
        "rp.nested": "- Dans l'ouverture de **{host}** : {parts}",
        "rp.head": "| Pièce | Orientation | Taille (mm) | Bordure | Supports | Pourquoi |",
        "rp.with": " + {name} (filament {n})", "rp.tree": "arborescent", "rp.none": "non",
        "rp.volume": "- Quantité : {n} objets sur {plates} {plates:plaque|plaques} (duplicata × {dup}, plaques max. {max})",
        "rp.check": "## Vérification dans Bambu Studio",
        "o.modelled": "comme modélisée", "o.axis": "{axis} en bas", "o.face": "face {vec} en bas",
        "o.up": "{key} en haut (bambu.json)",
        "r.sup_on_json": "supports oui (bambu.json)", "r.sup_off_json": "supports non (bambu.json)",
        "r.sup_on_all": "supports pour toutes les pièces (choisi)",
        "r.sup_off_all": "supports désactivés pour toutes les pièces (choisi)",
        "r.sup_on": "supports : {n} {n:zone|zones} en porte-à-faux, {area} mm², la plus grande {big} mm² (plus plate que "
                    "{slope}° par rapport à l'horizontale)",
        "r.islands": ", {n} {n:îlot|îlots} sans rien en dessous",
        "r.rim": " ; bord inférieur ignoré (dépasse de {mm} mm la première couche)",
        "r.sup_off": "pas de supports : {why}", "r.overhang": "{area} mm² de porte-à-faux",
        "r.no_overhang": "pas de porte-à-faux", "r.ignored": " (ignorés : {list})",
        "i.spots": "{n} {n:point|points}", "i.ledges": "{n} {n:rebord|rebords}", "i.bridges": "{n} {n:pont|ponts}", "i.bed rims": "{n} {n:bord au plateau|bords au plateau}",
        "r.rests": "centre de gravité à {mm} mm au-delà de l'appui : ce côté repose sur les supports",
        "r.brim_json": "bordure {mm} mm (bambu.json)", "r.no_brim_json": "pas de bordure (bambu.json)",
        "r.no_brim_all": "bordure désactivée pour toutes les pièces (choisi)",
        "b.lever_rest": "appui de {w} mm de large, {o} mm au-delà", "b.lever": "à {m} mm du bord de l'appui",
        "b.tall": "haute et étroite : centre de gravité à {h} mm de haut, {lever} (rapport {r})",
        "b.tips": "centre de gravité sur ou hors du bord de l'appui : bascule",
        "b.small_contact": "petit appui sur le plateau {a} mm²",
        "b.warp_long": "{warp}, empreinte de {l} mm de long",
        "b.warp_small": "{warp}, petite pièce ({a} mm² sur le plateau, {l} mm de long) : se décolle facilement",
        "b.all": "bordure sur toutes les pièces (choisi)",
        "r.brim": "bordure {mm} mm : {why}",
        "r.no_brim": "pas de bordure : {a} mm² sur le plateau, stable (rapport {r})",
        "wp.chamber": "{typ} {i} demande une chambre chauffée ({c} °C)",
        "wp.bed": "{typ} {i} demande un plateau chauffé ({c} °C)", "wp.warps": "{typ} {i} gauchit",
        "wp.filament": "filament",
        "r.function": "pièce {fn} (bambu.json)",
        "r.small": "petite pièce ({s} mm, {v} cm³) : 4 parois, presque pleine",
        "r.walls_json": "{n} parois (bambu.json)", "r.infill_json": "remplissage {v} (bambu.json)",
        "r.rectilinear": "remplissage rectiligne (nécessaire pour 100 %)", "r.setting_json": "{k} = {v} (bambu.json)",
        "r.strength": "résistance : {note}, {deg}° hors des couches",
        "ld.along": "charge selon {spec} (bambu.json)",
        "ld.longest": "charge selon son côté le plus long ({axis}, {mm} mm)",
        "w.load": "la charge passe à {deg}° à travers les couches (le sens faible) : {advice}",
        "w.load_up": "choisissez un \"up\" dans bambu.json qui couche l'axe de charge à plat",
        "w.load_none": "aucune des orientations testées qui tiennent ne le couche à plat ; vérifiez \"load_axis\" ou "
                       "définissez un \"up\" dans bambu.json, ou tournez la pièce dans Bambu Studio",
        "w.sup_off": "pas de supports (choisi), mais {area} mm² de porte-à-faux en ont besoin",
        "w.brim_off": "pas de bordure (choisi), mais cette pièce est haute/étroite ou a peu d'appui sur le plateau",
        "w.fit": "ne tient pas sur l'imprimante ({x} x {y} x {z} mm{brim} ; utile {ux} x {uy} x {uz})",
        "w.fit_brim": " + bordure de {mm} mm",
        "w.steep": "{a} mm² plus raides que {deg}° par rapport à la verticale (règle de conception SOMA) sans "
                   "supports : vérifiez l'aperçu",
        "w.no_contact": "presque aucun contact avec le plateau : la pièce repose sur une arête ou un point",
        "w.tips_far": "le centre de gravité est trop loin hors de l'appui pour que les supports le portent : la pièce "
                      "bascule, choisissez une autre orientation (\"up\" dans bambu.json)",
        "w.tips": "le centre de gravité est hors de l'appui et il n'y a pas de supports : la pièce bascule, "
                  "choisissez une autre orientation (\"up\" dans bambu.json)",
        "w.tower": "se trouve à l'emplacement de la tour de nettoyage (aucune autre place sur la plaque) : dans Bambu "
                   "Studio, déplacez la tour vers un endroit libre avant la découpe",
        "w.no_spot": "aucune place libre sur la plaque (trop grande, ou bloquée par les zones interdites de l'imprimante)",
        "w.filament": "demande le filament {n}, le modèle en a {have} : imprimée avec le filament 1. Ajoutez le "
                      "filament {n} dans Bambu Studio et affectez-le à cette pièce",
        "w.lift": "une pièce fusionnée descend sous le fond de cette pièce : elle la soulève du plateau",
        "c.skipped": "vérification ignorée : Bambu Studio introuvable à {path} (définissez BAMBU_STUDIO)",
        "c.failed": "Bambu Studio n'a pas pu découper le projet : {err} (code {code})",
        "c.warns": "Bambu Studio signale (plaque {n}) : {msg}",
        "c.rim": "{name} : très probablement son bord inférieur arrondi ou chanfreiné, qui dépasse de {mm} mm la "
                 "première couche. Cela s'imprime bien sans supports ; Bambu Studio ne peut pas mettre de supports "
                 "aussi bas et le signale",
        "c.sliced_warn": "Bambu Studio a découpé {n:la plaque|les {n} plaques}, avec les avertissements ci-dessous ({s} s)",
        "c.sliced_ok": "Bambu Studio a découpé {n:la plaque|les {n} plaques} sans erreur ni avertissement ({s} s)",
        "c.pictures": "{n:image de la plaque|images des plaques} : {first}{n:| ... plate{n}.png}",
        "c.settings_ok": "tous les réglages par pièce ({n} {n:pièce|pièces}) ont été conservés au chargement dans Bambu Studio",
        "c.missing": "{name} : absent après le chargement", "c.diff": "{name} : {list}",
        "c.plates": "Bambu Studio voit {g} {g:plaque|plaques}, Orientr en a écrit {n}",
        "c.gcode": "seulement {g} {g:plaque|plaques} sur {n} ont produit du G-code (plaque vide ?)",
        "ta.old": "Le modèle a été enregistré avec Bambu Studio {saved}, la version installée est {inst} : Bambu a "
                  "peut-être modifié ses préréglages d'imprimante et de filament depuis. Ouvrez {file} dans Bambu "
                  "Studio, vérifiez l'imprimante, le filament et le processus, et enregistrez-le à nouveau",
        "e.filament": "le filament {name!r} n'a pas de préréglage Bambu Studio pour la {printer} ; par exemple : {examples}",
        "e.printer": "imprimante inconnue {name!r} ; Bambu Studio connaît : {names}",
        "e.nozzle_size": "une buse de {size} mm ne convient pas à la {printer} ; choisissez parmi : {sizes}",
        "e.no_template": "pas encore de modèle pour la {printer}. Créez-le une fois dans la fenêtre de Bambu Studio "
                         "(pas en ligne de commande) :\n  1. Ouvrez Bambu Studio, choisissez la {printer} avec la "
                         "buse 0,4 (filament et processus au choix).\n  2. Posez un petit objet sur le plateau.\n  "
                         "3. Fichier > Enregistrer le projet sous > {folder} (nom au choix).\nPuis relancez.",
        "e.no_parts": "rien à imprimer : toutes les pièces sont exclues (ou fusionnées dans une pièce exclue)",
        "e.max_plates": "{n} objets demandent {need} plaques, plus que le maximum de {max} : moins de duplicata ou de copies "
                        "d'une pièce, ou plus de plaques max.",
        "e.no_build": "aucun build trouvé : lancez d'abord `soma build`",
    },
}
REPORT["en"]["r.rim_angle"] = ("support threshold {deg}° instead of {base}° for this part, so that Bambu Studio leaves "
                               "the bottom edge alone too (the real overhang keeps its support)")
REPORT["de"]["r.rim_angle"] = ("Stützwinkel {deg}° statt {base}° für dieses Teil, damit auch Bambu Studio die "
                               "Unterkante in Ruhe lässt (der echte Überhang behält seine Stützen)")
REPORT["fr"]["r.rim_angle"] = ("angle de support {deg}° au lieu de {base}° pour cette pièce, pour que Bambu Studio "
                               "laisse aussi le bord inférieur tranquille (le vrai porte-à-faux garde ses supports)")
# the report's check line when Bambu Studio only gave its standard notes for the filament (2026-11-22)
STRINGS["en"]["c.sliced_std"] = ("Bambu Studio sliced {n:the plate|all {n} plates} without errors ({s} s); below {k} standard "
                                 "{k:note|notes} it always gives for this filament, nothing to do")
STRINGS["de"]["c.sliced_std"] = ("Bambu Studio hat {n:die Druckplatte|alle {n} Druckplatten} ohne Fehler gesliced ({s} s); {k:der "
                                 "Standardhinweis unten kommt|die {k} Standardhinweise unten kommen} bei diesem Filament immer, "
                                 "nichts zu tun")
STRINGS["fr"]["c.sliced_std"] = ("Bambu Studio a découpé {n:la plaque|les {n} plaques} sans erreur ({s} s) ; ci-dessous {k} "
                                 "{k:remarque standard|remarques standard} qu'il donne toujours pour ce filament, rien à faire")
# after a standard warning of Bambu Studio (its own text stays in Bambu Studio's language); was English only (2026-11-23)
STRINGS["en"]["c.standard_note"] = ("[Standard: this warning is always given by Bambu Studio for this filament. Read it "
                                    "for your information, but it is completely normal.]")
STRINGS["de"]["c.standard_note"] = ("[Standard: diese Warnung gibt Bambu Studio bei diesem Filament immer. Zur "
                                    "Information, sie ist ganz normal.]")
STRINGS["fr"]["c.standard_note"] = ("[Standard : Bambu Studio donne toujours cet avertissement pour ce filament. À lire "
                                    "pour information, c'est tout à fait normal.]")
# the two files at the end of a run; was English only (2026-11-23)
STRINGS["en"]["run.written"] = "Written: {out}\nReport:  {report}"
STRINGS["de"]["run.written"] = "Geschrieben: {out}\nBericht:     {report}"
STRINGS["fr"]["run.written"] = "Écrit :   {out}\nRapport : {report}"
# a part that does not fit the printer stops the build with this (2026-11-22)
STRINGS["en"]["e.no_fit"] = ("Too big for the {printer}: {parts}. Choose a bigger printer, switch the part off under "
                             "Parts, or set Brim to never if only the brim does not fit.")
STRINGS["de"]["e.no_fit"] = ("Zu groß für den {printer}: {parts}. Einen größeren Drucker wählen, das Teil unter Teile abwählen, "
                             "oder Umrandung auf nie stellen, wenn nur die Umrandung nicht passt.")
STRINGS["fr"]["e.no_fit"] = ("Trop grand pour la {printer} : {parts}. Choisissez une imprimante plus grande, "
                             "désactivez la pièce dans Pièces, ou mettez Bordure sur jamais si seule la bordure dépasse.")
# status line when GitHub could not be reached (2026-11-22): no "up to date" without a check
STRINGS["en"]["s.orientr_offline"] = "Orientr {v}: No internet, update not checked"
STRINGS["de"]["s.orientr_offline"] = "Orientr {v}: Offline, Update nicht geprüft"
STRINGS["fr"]["s.orientr_offline"] = "Orientr {v} : Hors ligne, mise à jour non vérifiée"
# Analyze: Bambu Studio's standard warnings for the filament, once and short (2026-11-22)
STRINGS["en"]["pv.standard"] = "ℹ  Standard notes for this filament (always shown by Bambu Studio, nothing to do): {msgs}"
STRINGS["de"]["pv.standard"] = ("ℹ  Standardhinweise für dieses Filament (zeigt Bambu Studio immer, nichts zu tun): "
                                "{msgs}")
STRINGS["fr"]["pv.standard"] = ("ℹ  Remarques standard pour ce filament (toujours affichées par Bambu Studio, rien à "
                                "faire) : {msgs}")
# SOMA's own files not as expected (a SOMA update): a clear message instead of a Python error (2026-11-22)
STRINGS["en"]["e.soma_changed"] = ("SOMA's own files are not as Orientr expects ({what}): SOMA was probably "
                                   "updated. Please report it, with SOMA's version; orientr --selftest shows the details.")
STRINGS["de"]["e.soma_changed"] = ("SOMAs eigene Dateien sind nicht so, wie Orientr sie erwartet ({what}): "
                                   "SOMA wurde wahrscheinlich aktualisiert. Bitte melden, mit der SOMA-Version; "
                                   "orientr --selftest zeigt die Einzelheiten.")
STRINGS["fr"]["e.soma_changed"] = ("Les fichiers de SOMA ne sont pas comme Orientr les attend ({what}) : SOMA a "
                                   "probablement été mis à jour. Merci de le signaler, avec la version de SOMA ; "
                                   "orientr --selftest donne les détails.")
# Bambu Studio's profiles read once (after installing or a Studio update): about 2 minutes, announced (2026-11-22)
STRINGS["en"].update({
    "p.reading": "Reading Bambu Studio's printer, filament and process presets (only the first time and after a Bambu "
                 "Studio update, about 2 minutes)...",
    "p.done": "Bambu Studio's presets read: {n} presets in {s} s.",
})
STRINGS["de"].update({
    "p.reading": "Die Drucker-, Filament- und Prozessprofile von Bambu Studio werden gelesen (nur beim ersten Mal "
                 "und nach einem Bambu-Studio-Update, etwa 2 Minuten)...",
    "p.done": "Profile von Bambu Studio gelesen: {n} Profile in {s} s.",
})
STRINGS["fr"].update({
    "p.reading": "Lecture des préréglages d'imprimante, de filament et de processus de Bambu Studio (seulement la "
                 "première fois et après une mise à jour de Bambu Studio, environ 2 minutes)...",
    "p.done": "Préréglages de Bambu Studio lus : {n} préréglages en {s} s.",
})
# 2026-11-22: duplicates and copies up to 200, typed in, with a guard against projects too big to handle
STRINGS["en"].update({
    "f.copies": "Copies of {name}", "ps.number": "Number: ", "n.range": "A whole number {lo}..{hi}.",
    "e.too_many": "{n} objects is too many for one project (at most {max}): lower Duplicates or a part's copies.",
    "e.too_big": "{n} objects with {tris} million triangles is too big for Bambu Studio (at most {max} million): "
                 "lower Duplicates or a part's copies.",
    "e.memory": "{n} objects: not enough memory on this PC. Lower Duplicates or a part's copies.",
})
STRINGS["de"].update({
    "f.copies": "Kopien von {name}", "ps.number": "Anzahl: ", "n.range": "Eine ganze Zahl {lo}..{hi}.",
    "e.too_many": "{n} Objekte sind zu viele für ein Projekt (höchstens {max}): weniger Duplikate oder Kopien "
                  "eines Teils.",
    "e.too_big": "{n} Objekte mit {tris} Millionen Dreiecken sind zu groß für Bambu Studio (höchstens {max} "
                 "Millionen): weniger Duplikate oder Kopien eines Teils.",
    "e.memory": "{n} Objekte: nicht genug Arbeitsspeicher auf diesem PC. Weniger Duplikate oder Kopien eines Teils.",
})
STRINGS["fr"].update({
    "f.copies": "Copies de {name}", "ps.number": "Nombre : ", "n.range": "Un nombre entier {lo}..{hi}.",
    "e.too_many": "{n} objets, c'est trop pour un projet (au plus {max}) : moins de duplicata ou de copies "
                  "d'une pièce.",
    "e.too_big": "{n} objets avec {tris} millions de triangles, c'est trop pour Bambu Studio (au plus {max} "
                 "millions) : moins de duplicata ou de copies d'une pièce.",
    "e.memory": "{n} objets : pas assez de mémoire sur ce PC. Moins de duplicata ou de copies d'une pièce.",
})
# 2026-11-22: the project line and the messages a user of the form can meet, in every language (the options of the
# command line and the keys of bambu.json are English words, so their messages stay English)
STRINGS["en"].update({
    "f.project": "Project: {name}",
    "e.no_printable": "no printable parts (all are references, hardware or skipped)",
    "e.export_failed": "soma export failed:\n{out}",
    "e.export_missing": "soma export wrote no file for {name!r} ({file})",
    "e.stl": "cannot read {file}: not an STL file",
    "e.mesh_empty": "{name}: the exported mesh is empty or has no volume",
    "e.tpl_read": "{file} cannot be read as a Bambu Studio project ({err})",
    "e.tpl_no_settings": "{file} is not a Bambu Studio project (no project settings)",
    "e.tpl_app": "{file} was not saved by Bambu Studio ({app})",
    "e.tpl_unusable": "{file} has no usable project settings",
    "e.tpl_gcode": "{file} has no real printer start G-code: it was not saved from the Bambu Studio window (the command "
                   "line leaves the presets unresolved). Save the template from Bambu Studio.",
    "e.locked": "cannot write {path}: is it open in Bambu Studio? Close it there and run again.",
    "e.no_processes": "no process presets for {printer} found in Bambu Studio's preset folder",
    "e.no_filaments": "no filament presets for {printer} found in Bambu Studio's preset folder",
    "e.process_near": "unknown process {name!r} for the {printer}; did you mean: {names}",
    "e.process_list": "unknown process {name!r} for the {printer}; choose from: {names}",
    "e.layer": "layer height {lh} mm is outside this printer's range {lo}..{hi} mm",
    "e.json": "bambu.json is not valid JSON (line {line}): {msg}",
    "e.not_model": "run this in a SOMA model folder (with model.py and .soma)",
    "v.unknown_app": "unknown application",
    "rp.k_layer_height": "layer {v} mm", "rp.k_wall_loops": "walls {v}", "rp.k_sparse_infill_density": "infill {v}",
    "rp.k_sparse_infill_pattern": "infill pattern {v}",
})
STRINGS["de"].update({
    "f.project": "Projekt: {name}",
    "e.no_printable": "keine druckbaren Teile (alle sind Referenzen, Normteile oder ausgeschlossen)",
    "e.export_failed": "soma export ist fehlgeschlagen:\n{out}",
    "e.export_missing": "soma export hat keine Datei für {name!r} geschrieben ({file})",
    "e.stl": "{file} kann nicht gelesen werden: keine STL-Datei",
    "e.mesh_empty": "{name}: das exportierte Netz ist leer oder hat kein Volumen",
    "e.tpl_read": "{file} kann nicht als Bambu-Studio-Projekt gelesen werden ({err})",
    "e.tpl_no_settings": "{file} ist kein Bambu-Studio-Projekt (keine Projekteinstellungen)",
    "e.tpl_app": "{file} wurde nicht mit Bambu Studio gespeichert ({app})",
    "e.tpl_unusable": "{file} hat keine brauchbaren Projekteinstellungen",
    "e.tpl_gcode": "{file} hat keinen echten Start-G-Code des Druckers: Die Datei wurde nicht im Bambu-Studio-Fenster "
                   "gespeichert (die Kommandozeile lässt die Profile offen). Die Vorlage in Bambu Studio speichern.",
    "e.locked": "{path} kann nicht geschrieben werden: Ist die Datei in Bambu Studio geöffnet? Dort schließen und "
                "erneut starten.",
    "e.no_processes": "keine Prozessprofile für {printer} in Bambu Studios Profilordner gefunden",
    "e.no_filaments": "keine Filamentprofile für {printer} in Bambu Studios Profilordner gefunden",
    "e.process_near": "unbekannter Prozess {name!r} für den {printer}; meinten Sie: {names}",
    "e.process_list": "unbekannter Prozess {name!r} für den {printer}; wählen Sie aus: {names}",
    "e.layer": "Schichthöhe {lh} mm liegt außerhalb des Bereichs dieses Druckers ({lo}..{hi} mm)",
    "e.json": "bambu.json ist kein gültiges JSON (Zeile {line}): {msg}",
    "e.not_model": "in einem SOMA-Modellordner ausführen (mit model.py und .soma)",
    "v.unknown_app": "unbekanntes Programm",
    "rp.k_layer_height": "Schicht {v} mm", "rp.k_wall_loops": "Wände {v}", "rp.k_sparse_infill_density": "Füllung {v}",
    "rp.k_sparse_infill_pattern": "Füllmuster {v}",
})
STRINGS["fr"].update({
    "f.project": "Projet : {name}",
    "e.no_printable": "aucune pièce imprimable (toutes sont des références, de la visserie ou exclues)",
    "e.export_failed": "échec de soma export :\n{out}",
    "e.export_missing": "soma export n'a écrit aucun fichier pour {name!r} ({file})",
    "e.stl": "impossible de lire {file} : ce n'est pas un fichier STL",
    "e.mesh_empty": "{name} : le maillage exporté est vide ou n'a pas de volume",
    "e.tpl_read": "{file} ne peut pas être lu comme projet Bambu Studio ({err})",
    "e.tpl_no_settings": "{file} n'est pas un projet Bambu Studio (pas de paramètres de projet)",
    "e.tpl_app": "{file} n'a pas été enregistré par Bambu Studio ({app})",
    "e.tpl_unusable": "{file} n'a pas de paramètres de projet utilisables",
    "e.tpl_gcode": "{file} n'a pas de vrai G-code de démarrage de l'imprimante : il n'a pas été enregistré depuis la "
                   "fenêtre de Bambu Studio (la ligne de commande laisse les préréglages non résolus). Enregistrez le "
                   "modèle depuis Bambu Studio.",
    "e.locked": "impossible d'écrire {path} : est-il ouvert dans Bambu Studio ? Fermez-le et relancez.",
    "e.no_processes": "aucun préréglage de processus pour {printer} dans le dossier des préréglages de Bambu Studio",
    "e.no_filaments": "aucun préréglage de filament pour {printer} dans le dossier des préréglages de Bambu Studio",
    "e.process_near": "processus inconnu {name!r} pour la {printer} ; vouliez-vous dire : {names}",
    "e.process_list": "processus inconnu {name!r} pour la {printer} ; choisissez parmi : {names}",
    "e.layer": "la hauteur de couche de {lh} mm est hors de la plage de cette imprimante ({lo}..{hi} mm)",
    "e.json": "bambu.json n'est pas un JSON valide (ligne {line}) : {msg}",
    "e.not_model": "lancez ceci dans le dossier d'un modèle SOMA (avec model.py et .soma)",
    "v.unknown_app": "application inconnue",
    "rp.k_layer_height": "couche {v} mm", "rp.k_wall_loops": "parois {v}",
    "rp.k_sparse_infill_density": "remplissage {v}", "rp.k_sparse_infill_pattern": "motif de remplissage {v}",
})
# 2026-11-22: more colours, from a template with several filaments; colour names in the user's language
STRINGS["en"].update({
    "col.black": "black", "col.white": "white", "col.grey": "grey", "col.red": "red", "col.orange": "orange",
    "col.yellow": "yellow", "col.green": "green", "col.blue": "blue", "col.brown": "brown", "col.purple": "purple",
    "col.pink": "pink", "col.dark grey": "dark grey",
    "r.fil_colour": "filament {fil}: closest to the part's colour ({colour})",
    "r.fil_chosen": "filament {fil} (chosen)",
    "w.fil_far": "no filament close to {colour}: printed with filament {fil}. Add a {colour} filament to the color "
                 "template, or let Orientr make the filaments (Colors in the form)",
    "f.colors": "Colors",
})
STRINGS["de"].update({
    "col.black": "Schwarz", "col.white": "Weiß", "col.grey": "Grau", "col.red": "Rot", "col.orange": "Orange",
    "col.yellow": "Gelb", "col.green": "Grün", "col.blue": "Blau", "col.brown": "Braun", "col.purple": "Lila",
    "col.pink": "Rosa", "col.dark grey": "Dunkelgrau",
    "r.fil_colour": "Filament {fil}: am nächsten an der Farbe des Teils ({colour})",
    "r.fil_chosen": "Filament {fil} (gewählt)",
    "w.fil_far": "kein Filament nahe an {colour}: gedruckt mit Filament {fil}. Ein Filament in {colour} zur "
                 "Farbvorlage hinzufügen oder die Filamente von Orientr machen lassen (Farben im Formular)",
    "f.colors": "Farben",
})
STRINGS["fr"].update({
    "col.black": "noir", "col.white": "blanc", "col.grey": "gris", "col.red": "rouge", "col.orange": "orange",
    "col.yellow": "jaune", "col.green": "vert", "col.blue": "bleu", "col.brown": "marron", "col.purple": "violet",
    "col.pink": "rose", "col.dark grey": "gris foncé",
    "r.fil_colour": "filament {fil} : le plus proche de la couleur de la pièce ({colour})",
    "r.fil_chosen": "filament {fil} (choisi)",
    "w.fil_far": "aucun filament proche de {colour} : imprimée avec le filament {fil}. Ajoutez un filament {colour} "
                 "au modèle de couleurs, ou laissez Orientr faire les filaments (Couleurs dans le formulaire)",
    "f.colors": "Couleurs",
})
# 2026-11-23: the model's colours on a colour template's filaments, and a colour per part chosen by hand (C)
STRINGS["en"].update({
    "rp.recoloured": "- Colors: the template's filaments got the model's colors: {colours}. Orientr estimated the "
                     "purge volumes for them (a little generous)",
    "r.fil_own_colour": "filament {fil}: the color chosen for the part ({colour})",
    "w.fil_merged": "the model has more colors than the template's {have} filaments: {colour} is printed with filament "
                    "{fil}. Choose a template with more filaments, or let Orientr make the filaments (Colors in the "
                    "form)",
    "v.col_own": "Chosen",
})
STRINGS["de"].update({
    "rp.recoloured": "- Farben: die Filamente der Vorlage haben die Farben des Modells bekommen: {colours}. Orientr hat "
                     "die Spülmengen dafür geschätzt (etwas großzügig)",
    "r.fil_own_colour": "Filament {fil}: die für das Teil gewählte Farbe ({colour})",
    "w.fil_merged": "das Modell hat mehr Farben als die {have} Filamente der Vorlage: {colour} wird mit Filament {fil} "
                    "gedruckt. Eine Vorlage mit mehr Filamenten wählen oder die Filamente von Orientr machen lassen "
                    "(Farben im Formular)",
    "v.col_own": "Gewählt",
})
STRINGS["fr"].update({
    "rp.recoloured": "- Couleurs : les filaments du modèle ont reçu les couleurs du modèle SOMA : {colours}. Orientr a "
                     "estimé les volumes de purge (un peu généreux)",
    "r.fil_own_colour": "filament {fil} : la couleur choisie pour la pièce ({colour})",
    "w.fil_merged": "le modèle a plus de couleurs que les {have} filaments du modèle de couleurs : {colour} est "
                    "imprimée avec le filament {fil}. Choisissez un modèle avec plus de filaments, ou laissez Orientr "
                    "faire les filaments (Couleurs dans le formulaire)",
    "v.col_own": "Choisie",
})
# one filament per colour, made by Orientr; Bambu Lab's own colours (2026-11-23)
STRINGS["en"].update({
    "w.colour_unavailable": "{colour} is not sold in this filament: printed with filament {fil}, the nearest color "
                            "Bambu Lab has",
    "v.auto_model": "Auto from SOMA model",
    "v.manual": "Manual  ·  {name}",
    "v.col_model": "As in the SOMA model",
    "v.col_project": "Project color ({name})",
    "f.colour_of": "Color of {name}",
    # at most 2 lines of 57 (SOMA's terminal), each sentence wrapped on its own
    "h.colours2": "{n} {n:filament|filaments}, one per color. Manual: This color, a part's own: C in Parts.",
    "h.colours_far2": "⚠ {n} {n:color is|colors are} not sold in this filament: See Parts.",
    "help.parts_c": "↑↓  Choose   Space  On/Off   ←→ or number  Copies\nC  Color   A  All   N  None   Enter  Done",
    "w.colour_unmixable": "{colour} cannot be mixed closely: printed with filament {fil}, the nearest mix",
    "e.mix_mode": "unknown color mixing mode {mode}; Bambu Studio has: {modes}",
    "e.mix_printer": "the {printer} has one hotend: color mixing changes filament on every sub-layer there (much "
                     "waste, risk of clogging). Choose a printer with more hotends (H2D, H2C, H3C, X2D)",
    "v.mix": "Mix  ·  {mode} ({filament})",
    "h.mix": "Load {bases}, {m} mixed (slow).",
    "h.mix_far": "⚠ {n} {n:color|colors} cannot be mixed closely: See Parts.",
})
STRINGS["de"].update({
    "w.colour_unavailable": "{colour} gibt es für dieses Filament nicht: gedruckt mit Filament {fil}, der nächsten "
                            "Farbe von Bambu Lab",
    "v.auto_model": "Auto aus SOMA-Modell",
    "v.manual": "Manuell  ·  {name}",
    "v.col_model": "Wie im SOMA-Modell",
    "v.col_project": "Projektfarbe ({name})",
    "f.colour_of": "Farbe von {name}",
    "h.colours2": "{n} {n:Filament|Filamente}, eins je Farbe. Manuell: diese Farbe, je Teil: C unter Teile.",
    "h.colours_far2": "⚠ {n} {n:Farbe gibt|Farben gibt} es für dieses Filament nicht: Siehe Teile.",
    "help.parts_c": "↑↓  Wählen   Leertaste  An/Aus   ←→ oder Zahl  Kopien\nC  Farbe   A  Alle   N  Keine   Enter  Fertig",
    "w.colour_unmixable": "{colour} lässt sich nicht genau mischen: gedruckt mit Filament {fil}, der nächsten Mischung",
    "e.mix_mode": "unbekannter Farbmischmodus {mode}; Bambu Studio hat: {modes}",
    "e.mix_printer": "der {printer} hat ein Hotend: Farbmischen wechselt dort bei jeder Teilschicht das Filament (viel "
                     "Abfall, Verstopfungsgefahr). Einen Drucker mit mehr Hotends wählen (H2D, H2C, H3C, X2D)",
    "v.mix": "Mischen  ·  {mode} ({filament})",
    "h.mix": "Einlegen: {bases}, {m} gemischt.",
    "h.mix_far": "⚠ {n} {n:Farbe lässt|Farben lassen} sich nicht genau mischen: Siehe Teile.",
})
STRINGS["fr"].update({
    "w.colour_unavailable": "{colour} n'existe pas pour ce filament : imprimée avec le filament {fil}, la couleur Bambu "
                            "Lab la plus proche",
    "v.auto_model": "Auto (modèle SOMA)",
    "v.manual": "Manuel  ·  {name}",
    "v.col_model": "Comme dans le modèle SOMA",
    "v.col_project": "Couleur du projet ({name})",
    "f.colour_of": "Couleur de {name}",
    "h.colours2": "{n} filament{n:|s}, un par couleur. Manuel : Cette couleur, par pièce : C dans Pièces.",
    "h.colours_far2": "⚠ {n} couleur{n:|s} n'exist{n:e|ent} pas pour ce filament : Voir Pièces.",
    "help.parts_c": "↑↓  Choisir   Espace  Oui/Non   ←→ ou nombre  Copies\nC  Couleur   A  Toutes   N  Aucune   Entrée  Terminé",
    "w.colour_unmixable": "{colour} ne se mélange pas de près : imprimée avec le filament {fil}, le mélange le plus "
                          "proche",
    "e.mix_mode": "mode de mélange de couleurs {mode} inconnu ; Bambu Studio a : {modes}",
    "e.mix_printer": "la {printer} a une seule buse : le mélange change de filament à chaque sous-couche (beaucoup de "
                     "déchets, risque de bouchage). Choisissez une imprimante à plusieurs buses (H2D, H2C, H3C, X2D)",
    "v.mix": "Mélange  ·  {mode} ({filament})",
    "h.mix": "Charger : {bases}, {m} mélangé{m:|s}.",
    "h.mix_far": "⚠ {n} couleur{n:|s} ne se mélange{n:|nt} pas de près : Voir Pièces.",
})
for _code in STRINGS:
    STRINGS[_code].update(REPORT[_code])
