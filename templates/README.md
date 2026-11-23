# Templates: where they come from

Each `.3mf` file here is a Bambu Studio project saved in the Bambu Studio window, one per printer, with a small object
on the plate. Orientr takes the printer's settings from it (see the main README, *Templates*).

The settings inside them (`Metadata/project_settings.config`: printer, nozzle, filament and process values, and the
printer's start and end G-code) come from **Bambu Studio's system presets, Copyright (C) Bambu Lab, part of
[Bambu Studio](https://github.com/bambulab/BambuStudio), licensed under the GNU Affero General Public License version
3 (AGPL-3.0)**. They are passed on here under that license, unchanged, except that the Bambu account number Bambu
Studio writes into every saved project was removed.

Orientr's own code is licensed under the GNU General Public License version 3 (see `LICENSE` in the main
folder); GPL-3.0 and AGPL-3.0 may be combined (section 13 of both licences). "Bambu Lab" and "Bambu Studio" are names
of their owner; Orientr is not affiliated with or endorsed by Bambu Lab.
