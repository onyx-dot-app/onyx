# InputKeyValue

**Import:** `import { InputKeyValue, type KeyValue } from "@opal/components";`

An editable list of key/value pairs: two columns, per-row remove, an add-line action, and
built-in validation (empty keys, duplicate keys) with plural summary messages. All labels come
from `OpalStrings` (`keyValue*`), overridable per instance via the title/label props.

`valueType` defaults to `"text"`. Set `valueType="password"` for secret values.
This uses `InputPasswordTypeIn`, with its mask, reveal toggle, and session replay exclusion.
Keys remain plain text. Reveal and hide do not change values or validation.
Adding or removing rows hides password values so reveal state cannot move to another credential.
