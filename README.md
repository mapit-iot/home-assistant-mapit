# Mapit for Home Assistant: the official Mapit integration

Made and maintained by [Mapit](https://mapit.me). Mapit lists its official and approved apps at <https://developers.mapit.me/approved-apps>. Other projects that use Mapit are not endorsed by Mapit unless they are listed there.

The official Home Assistant integration for Mapit vehicle trackers. Sign in
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
| Status | At rest, vibration, in transit, offline, off or fall detection, as in the Mapit app (see below) |
| Last location | When that position was reported |
| Last communication | When the tracker last reported anything (diagnostic) |
| Mapit battery | The tracker's own battery, not the vehicle's, as last reported (diagnostic) |
| Vehicle voltage | The vehicle's supply seen by the tracker, in volts (diagnostic, off by default) |
| Odometer | The mileage stored in Mapit |
| Alert | The last alert the Mapit app sent you about the vehicle (see [Alerts](#alerts)) |

Everything is **last reported, not live**. A parked tracker reports less often, so check the
Last location and Last communication times before acting on a position. A vehicle voltage of
0 while the vehicle is stopped is normal: it is not a fault, a flat battery or a disconnection.
Some trackers report a fixed 12.0 V only to say they are connected to the vehicle's power, so the
voltage sensor is off by default; turn it on in the entity settings if you want it.

The status values, with the same labels as the Mapit app:

- `at_rest` **At rest**: the vehicle is parked.
- `buzz` **Vibration**: the tracker felt vibration while parked.
- `moving` **In transit**: the vehicle is moving.
- `no_comms` **Offline**: the tracker is not communicating.
- `hibernation` and `hibernation_requested` **Off**: hibernating or about to, to save battery.
- `tilt_detected` **Fall detection**: the vehicle may have fallen.

A vehicle that never reported a position or status, or reports one not listed here, shows
"unknown". The labels are translated into Spanish and Portuguese.

Vehicles whose subscription is cancelled, that are being transferred, or that have no tracker
show no position, as in the Mapit app.

## Alerts

The alerts the Mapit app sends to your phone also reach Home Assistant, so you can build
automations on them. Each one updates the vehicle's **Alert** entity and fires a `mapit_alert`
event. Only the alerts you have switched on in the Mapit app arrive, with these types:

- `movement_detected` **Movement detected**: the vehicle moved. This includes most ride starts,
  not only a moved parked vehicle.
- `geofence_entered` and `geofence_exited` **Geofence entry** and **Geofence exit**: the vehicle
  entered or left one of your Mapit geofences (zones in the app). `geofence` is its name.
- `ignition_on_detected` **Ignition left on**: parked with the ignition on.
- `fall_detected` **Fall detected**.
- `accident_detected` **Accident detected**, and `accident_contacts_notified` **Emergency contacts
  notified**, when Mapit sent the accident SMS to your emergency contacts.

Each alert has `occurred_at` (when it happened) and `notified_at` (when the Mapit app was told to
send it). The `mapit_alert` event also has `device_id`, the vehicle's device in Home Assistant.

Alerts arrive a minute or two after the event: fine for "arriving home", too slow for a theft
alarm. They are never a replacement for the Mapit app and its emergency SMS.

In the automation editor, pick the vehicle's **Alert** entity as the trigger and its **Type** as
the condition. In YAML, the `mapit_alert` event is the simplest trigger. This one opens the garage
when the vehicle enters the geofence called "Home":

```yaml
automation:
  - alias: Open the garage when the Vespa gets home
    triggers:
      - trigger: event
        event_type: mapit_alert
        event_data:
          type: geofence_entered
          geofence: Home
          device_id: 0123456789abcdef0123456789abcdef  # the Vespa's device id
    actions:
      - action: cover.open_cover
        target:
          entity_id: cover.garage_door
```

Find the device id in the address bar of the vehicle's device page. When you first add the
integration, alerts sent before that are not replayed. Alerts that arrive while Home Assistant is
off are delivered when it starts again, unless they were sent more than 15 minutes earlier: those
are skipped, so an automation never acts on stale news.

## Requirements

- Home Assistant 2026.10 or newer.
- The My Home Assistant integration (`my`), which is on by default (`default_config`). Mapit
  sends you back to Home Assistant through `my.home-assistant.io` after you sign in.
- A Mapit account with at least one vehicle.

## Install

With [HACS](https://hacs.xyz): add `https://github.com/mapit-iot/home-assistant-mapit` as a
custom repository (type Integration), install **Mapit** and restart Home Assistant. HACS installs
the [latest release](https://github.com/mapit-iot/home-assistant-mapit/releases/latest).

By hand: download the source of the
[latest release](https://github.com/mapit-iot/home-assistant-mapit/releases/latest), not `main`,
copy its `custom_components/mapit` into your Home Assistant `config/custom_components` folder and
restart Home Assistant. Home Assistant downloads `aiomapit` from PyPI on that first restart, so it
needs internet access.

## Set up

1. In Home Assistant, go to **Settings > Devices & services > Add integration** and pick
   **Mapit**.
2. Sign in with your Mapit account. Mapit asks for your password even if you are signed in,
   because the location of your vehicles is shared. Tick **Also allow vehicle location and last
   reported device status**: Home Assistant cannot show your vehicles without it.
3. The first time, `my.home-assistant.io` asks for your Home Assistant URL (it suggests
   `http://homeassistant.local:8123`). Enter the address you open Home Assistant at and press
   **Link account**. The address is stored only in that browser.
4. Home Assistant opens a **Name and assign** dialog that lists every vehicle, where you can choose
   an area for each. **Skip and finish** is fine too. Your vehicles appear.

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
once an hour, and when a new vehicle appears. The status says when there are new alerts, and
only then does Home Assistant read them, with one more request.

## Privacy

Home Assistant keeps the sign-in tokens, never your password. The position and status of your
vehicles, and the alerts with their geofence names, are stored by Home Assistant like any other
entity. Diagnostics downloads leave out
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
