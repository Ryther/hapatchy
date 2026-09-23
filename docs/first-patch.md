# Your first patch

[← Installation](installation.md) · [Settings reference →](reference.md)

This exercise changes an unused text file from `interval=30` to `interval=5`.
**Home Assistant does not read this demo file**, so the example does not change
any real device or integration. It lets you see how checking, applying and
reverting work before touching an important file.

You need HAPatchY installed and access to your HA configuration folder. In this
guide, a path such as `hapatchy_demo/settings.txt` is relative to that folder.

## 1. Create the target file

Create a folder named `hapatchy_demo`. Inside it, create `settings.txt` with
exactly these two lines, including a newline after the last line:

```text
mode=demo
interval=30
```

Use a plain-text editor and UTF-8 encoding. Do not save it as a rich-text document
or as `settings.txt.txt`. You can also download [the example file](examples/settings.txt).

The **target** is the file HAPatchY will change. At this point it should still
contain `interval=30`.

## 2. Create the patch source

Create a separate folder named `patches` in the configuration folder. Inside it,
create `demo_interval.patch` using [this downloadable patch](examples/interval.patch),
or copy the following exactly:

```diff
--- a/hapatchy_demo/settings.txt
+++ b/hapatchy_demo/settings.txt
@@ -1,2 +1,2 @@
 mode=demo
-interval=30
+interval=5
```

There is **one leading space** before `mode=demo`. Preserve that space and the
final newline. Do not copy the Markdown fence lines (the lines with three backticks).

The first two lines name the target. A line starting with `-` is removed; a line
starting with `+` is added. A line starting with a space is unchanged **context**:
it helps identify the right place. The `@@` line describes the hunk's line counts.
For real patches, ask their author to generate a correct unified diff instead of
manually inventing those counts.

Your folders should now look like this:

```text
configuration.yaml
hapatchy_demo/
  settings.txt
patches/
  demo_interval.patch
```

## 3. Add the patch in Home Assistant

Open **Settings → Devices & services → HAPatchY → Add patch**. Enter:

| Field | Enter |
| --- | --- |
| Name | `Demo interval` |
| Target path | `hapatchy_demo/settings.txt` |
| Watch directory | `hapatchy_demo` |
| Watch pattern | Leave empty |
| Source type | `local` |
| Local path or direct HTTPS URL | `patches/demo_interval.patch` |

The watch directory is the folder to monitor for file replacements. Leaving the
pattern empty selects the specific target within that directory. The source is
**the patch**, not another copy of the target.

On the next screen:

- Keep **Enabled**, **Check at Home Assistant startup**, and **Back up before applying** on.
- Turn **Apply compatible patches automatically** **off** for this exercise.
- Leave the optional SHA-256 empty and the wait at **1.5 seconds**.
- Submit the form.

HAPatchY should create a sensor named **Demo interval status**. The state should
be **Applicable** (`applicable` in Developer tools), and the file should still
contain `interval=30`. A brief `unknown` state before the initial check is normal.
If you see another status, stop and use [troubleshooting](troubleshooting.md).

## 4. Find the patch ID and apply once

1. Open **Developer tools → States** and search for `Demo interval` or `hapatchy`.
   If needed, open HAPatchY's entity list to find the exact sensor entity ID.
2. Select its status sensor. In its attributes, copy **`patch_id`**.
   This generated value is different from the sensor's `entity_id`.
3. Open **Developer tools → Actions** and choose **HAPatchY: Apply**
   (`hapatchy.apply`). Paste the value into **Patch ID** and perform the action.

If using YAML mode, replace the example value below with the ID you copied:

```yaml
action: hapatchy.apply
data:
  patch_id: "paste-your-patch-id-here"
```

Expected result:

- The sensor becomes **Applied**.
- `hapatchy_demo/settings.txt` contains `mode=demo` and `interval=5`.
- A backup exists under `.hapatchy/backups/<patch_id>/` in the configuration folder.
  Your editor may need **Show hidden files** to display `.hapatchy`.

Applying again should leave the already-patched file unchanged. This demo uses
`.txt`; no HA restart is needed to observe its contents.

## 5. Revert the change

Choose **HAPatchY: Revert** (`hapatchy.revert`) in Actions and use the same patch ID.
The file should return to `interval=30`, and the sensor should become **Applicable**.

Revert first turns automatic application off and keeps it off. It then reverses
the current patch only if the file still matches exactly, making a mandatory
backup before writing. It does not blindly copy an old backup over the file.

## 6. Try automatic reapplication

1. Use the patch's settings menu on the HAPatchY page to **Reconfigure** it.
2. Keep the paths unchanged. Turn automatic application on and keep the startup
   check on, then save. The integration reloads and should apply the patch.
3. In your editor, replace the demo file with its original two lines:
   `mode=demo` and `interval=30`. This simulates an upstream update replacing a file.
4. Wait a few seconds. HAPatchY should restore `interval=5` and show **Applied**.

This is a simple local demonstration, not a test of a particular HACS update.
For real integrations, an update can also change the surrounding code, in which
case a **Conflict** is the correct result. Review the new upstream version and
obtain an updated patch; do not force the old one.

## 7. Clean up or move on

Run **Revert**, remove the demo patch using its menu, then delete the two demo
files/folders if you no longer need them. Removing a rule alone does not revert
its target. Backups are retained until you intentionally remove them.

For a real patch, verify its author, the exact upstream version, the target path
and the intended change. Read [the settings reference](reference.md) and keep a
separate backup before enabling automatic application.
