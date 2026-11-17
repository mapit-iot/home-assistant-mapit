# Mapit for Home Assistant

The official Home Assistant integration for [Mapit](https://mapit.me) vehicle trackers. Sign in
with your Mapit account and each of your vehicles appears in Home Assistant with its last
reported position and status.

## Beta

This integration is a beta, free for now. Use is subject to the Mapit
[Terms of Use](https://developers.mapit.me/terms) and
[Privacy Notice](https://developers.mapit.me/privacy), for personal, non-commercial use.

- It is free during the beta. That may change.
- There is no guarantee that it is available, complete or up to date, and it may change or stop
  working without notice.
- Do not rely on it for emergencies or anything safety-critical, such as recovering a stolen
  vehicle. Use the Mapit app and Mapit support for that.

## What you get

One device per vehicle on your Mapit account, with:

| Entity | What it shows |
| --- | --- |
| Tracker (the vehicle's name) | The last position the tracker reported |
| Status | Parked, moving, movement detected, no communication, going to hibernate or hibernating |
| Last location | When that position was reported |
| Last communication | When the tracker last reported anything (diagnostic) |
| Mapit battery | The tracker's own battery, not the vehicle's, as last reported (diagnostic) |
| Vehicle voltage | The vehicle's supply seen by the tracker, in volts (diagnostic, off by default) |
| Odometer | The mileage stored in Mapit |

Everything is **last reported, not live**. A parked tracker reports less often, so check the
Last location and Last communication times before acting on a position. A vehicle voltage of
0 while the vehicle is stopped is normal: it is not a fault, a flat battery or a disconnection.
Some trackers report a fixed 12.0 V only to say they are connected to the vehicle's power, so the
voltage sensor is off by default; turn it on in the entity settings if you want it.

Vehicles whose subscription is cancelled, that are being transferred, or that have no tracker
show no position, as in the Mapit app.

## Requirements

- Home Assistant 2026.10 or newer.
- The My Home Assistant integration (`my`), which is on by default (`default_config`). Mapit
  sends you back to Home Assistant through `my.home-assistant.io` after you sign in.
- A Mapit account with at least one vehicle.

## Install

With [HACS](https://hacs.xyz): add `https://github.com/mapit-iot/home-assistant-mapit` as a
custom repository (type Integration), install **Mapit** and restart Home Assistant.

By hand: copy `custom_components/mapit` into your Home Assistant `config/custom_components`
folder and restart Home Assistant.

## Set up

1. In Home Assistant, go to **Settings > Devices & services > Add integration** and pick
   **Mapit**.
2. Sign in with your Mapit account. Mapit asks for your password even if you are signed in,
   because the location of your vehicles is shared. Tick **Also allow vehicle location and last
   reported device status**: Home Assistant cannot show your vehicles without it.
3. You are sent back to Home Assistant and your vehicles appear.

Home Assistant stays connected while it keeps updating, up to a year. When the connection ends
(after a year, after 30 days without Home Assistant running, or if you remove it), Home
Assistant asks you to sign in again.

Restoring an old Home Assistant backup, or running two copies of Home Assistant with the same
Mapit entry, reuses an old sign-in and disconnects your account; sign in again to reconnect.

To disconnect Home Assistant, remove the integration, and remove **Home Assistant** from your
connected apps at <https://login.mapit.me/connections>.

## How it updates

Once a minute, Home Assistant asks Mapit for the status of all your vehicles in one request.
When nothing has changed, Mapit answers with a short "no change". If Mapit asks Home Assistant
to slow down, it waits as long as asked. The vehicle list (names, models, odometer) is read
once an hour, and when a new vehicle appears.

## Privacy

Home Assistant keeps the sign-in tokens, never your password. The position and status of your
vehicles are stored by Home Assistant like any other entity. Diagnostics downloads leave out
the tokens, positions, your email address and the names and plates of your vehicles.

## Help

Questions or problems: write to [atencioncliente@mapit.me](mailto:atencioncliente@mapit.me), or
open an issue at <https://github.com/mapit-iot/home-assistant-mapit/issues>.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The integration uses [aiomapit](https://github.com/mapit-iot/aiomapit) for every request.

## License

[MIT](LICENSE)
