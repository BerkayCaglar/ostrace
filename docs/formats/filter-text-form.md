# The filter text form

**Status:** written before anything reads it. `ostrace` **emits** this form and
does not parse it.

A filter in the viewer is four terms and three flags. This is how one is written
as a single line, so that it can be pasted into an issue, a chat message or a
commit body and set again by somebody else in a few seconds.

```
level:error -process:backupd subsystem:com.apple.network search:timeout
```

`Edit ▸ Copy Filter` puts this on the clipboard, and the *Saved filters* window
shows it under the name a filter was given.

## Why it is specified now

Nothing reads it yet. Fixing the spelling before a reader exists is the same
discipline the rest of `docs/formats/` applies: a form nobody specified is one
every reader guesses at differently, and the guesses are only discovered when
two of them disagree in public.

A reader is deliberately out of scope for this release. When one is written, the
rule it must follow is the one the invalid-regex path already follows: an
unparseable line leaves the standing filter alone and says precisely why. A
filter that half-applies is worse than one that does not apply.

## The terms

Terms are separated by a single space and appear in this order. A term that does
not narrow anything is **omitted**, so a filter showing everything writes as the
empty line.

| Term | Meaning | Written when |
| --- | --- | --- |
| `level:<name>` | Severity **threshold** — this level and above | the threshold is not `debug` |
| `process:<value>` | Process name contains `<value>`, or its pid equals it exactly | the field is not empty |
| `subsystem:<value>` | Subsystem contains `<value>` | the field is not empty |
| `search:<value>` | Message contains `<value>`, case-insensitively | the field is not empty and Regex is off |
| `regex:<value>` | Message matches the pattern `<value>`, case-insensitively | the field is not empty and Regex is on |

Every term must match: the line is a conjunction.

### Level names

The **enum name**, lowercased: `debug`, `info`, `notice`, `user_action`,
`error`, `fault`.

Not the display form. `Level.USER_ACTION` displays as `User Action`, and the
space in it is the one character the term separator claims — so the display form
would have to be quoted in exactly one case out of six, which is a rule nobody
would remember. The names here are what `Level.parse` already accepts.

`level` is a threshold rather than an equality because Apple's own values are
not severity-ordered. `docs/design/gui.md` §5 has the numbers.

### Negation

A leading `-` on the **key**:

```
-process:backupd
```

means *every record except this process*. Only `process` and `subsystem` can be
negated.

The sign is on the key rather than inside the value because process names and
subsystems really do contain hyphens, and a leading `-` inside a value would
need an escape rule of its own for the case where somebody means one.

### Patterns

`regex:` rather than a marker on the value.

The research this came from proposed `search:~timeout`, with `~` meaning "read
what follows as a pattern". That cannot express a literal search for a string
that *starts* with `~`, and this is not a theoretical case: `~` appears in real
device output — twice in the 8,000 committed fixture messages, once as the
banner `~~~~~ PCS Cache ~~~~~`, which is exactly the sort of thing somebody
pastes into the search box. Making the marker a key means no value is ever
inspected for a prefix.

## Quoting

A value is written bare unless it contains **whitespace, a double quote, or a
backslash**. When it does, it is wrapped in double quotes, and inside those a
backslash escapes a double quote or another backslash.

```
process:dasd
process:"two words"
process:"a \"quoted\" one"
process:"back\\slash"
```

Quoting only where it is needed, rather than always: this form exists to be
read, and a line where every value carries quotes is one people stop reading.

## What it does not carry

- **Whether the filter is applied.** It is a description of terms, not a
  command. Nothing about pasting one implies it should take effect.
- **The capture.** Two people comparing filters may be looking at different
  logs, and a form that named a file would look like it guaranteed otherwise.
- **Marks, the jump target, the theme, or anything else the window remembers.**
  Those are how somebody is reading, not what they are reading.

## Storage is a different format

The recent list and the saved filters are kept in `QSettings` as JSON, not as
this form. That is deliberate and the two requirements genuinely differ: this
form is lossy on purpose — it omits every term that does not narrow — and
settings have to round-trip exactly, entry by entry, including through a version
that spells a field differently. See `gui/filters.py`.
