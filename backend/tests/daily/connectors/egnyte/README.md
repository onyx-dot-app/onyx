# Egnyte Connector Test Setup

The daily tests in this directory read the Egnyte domain `app4danswer`.
They run on the daily schedule only, because Egnyte allows each access token 1,000 API calls per day.
One run makes about 50 calls.

## Credentials

The tests get a token with the password grant on each run. They read these test secrets:

| Secret | Value |
| --- | --- |
| `EGNYTE_CLIENT_ID` | API key of an internal Egnyte app with the scopes `Egnyte.filesystem`, `Egnyte.permission`, `Egnyte.user` and `Egnyte.group` |
| `EGNYTE_CLIENT_SECRET` | The app's secret |
| `EGNYTE_TEST_USERNAME` | An Egnyte administrator, `onyx_ci_admin` |
| `EGNYTE_TEST_PASSWORD` | That administrator's password |

## Corpus

The tests compare their results with this tree under `/Shared/OnyxPermTest`.
Do not change it without changing the tests.

| Folder | Own grants | Files |
| --- | --- | --- |
| `/` | Group `OnyxTestGroup`: Viewer; `onyx_std1`: Editor | — |
| `Inherits/` | — | `note.txt` |
| `InheritsPlusOwn/` | `chris_1_power`: Viewer | `note.txt` |
| `Override/` | `onyx_std1`: None | `note.txt` |
| `NoInherit/` | Inheritance off; `chris_1_power`: Viewer | `note.txt` |
| `NoInherit/Deep/` | Inheritance off; `onyx_std2`: Viewer | `note.txt` |
| `DefaultGroups/` | `All Power Users`, `All Standard Users` and `All Standard Users and Power Users`: Viewer; `onyx_std2`: Viewer Only | — |
| `Versions/` | — | `doc.txt`, uploaded twice; the second version is `Version two of the doc.` |
| `Big/` | — | `file_000.txt` to `file_119.txt` |

Each `note.txt` contains `Test note in /<folder>.`, for example `Test note in /NoInherit/Deep.`

`OnyxTestGroup` has the members `onyx_std1` and `chris_1_power`.
`onyx_std1` and `onyx_std2` are standard users, and `chris_1_power` is a power user.

`test_ids_survive_a_folder_rename` renames `Versions/` and then renames it back.
If a run stops between the two moves, rename `Versions Renamed/` to `Versions/`.
