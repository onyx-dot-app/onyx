# Internationalization Scripts

This directory contains scripts for automating the internationalization process of the SmartSearch/Onyx project.

## Available Scripts

### Original Scripts
- `bulk-i18n-replace.js` - Массовый скрипт замены русских текстов на i18n ключи
- `i18n-replace.js` - Основной скрипт для поиска и замены русских текстов

### Internationalized Versions
- `bulk-i18n-replace-i18n.js` - Internationalized version of bulk replacement script
- `i18n-replace-i18n.js` - Internationalized version of text replacement script

## Features

### Enhanced Regex Processing
The scripts now include improved regex processing with proper escaping:

```javascript
const regex = new RegExp(
  russianText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
  "g"
);
```

### Flexible Object Syntax
Support for both quoted and unquoted object keys:

```javascript
const replacements = {
  "Quoted text": "QUOTED_KEY",
  UnquotedText: "UNQUOTED_KEY",
};
```

### Auto-Import Detection
Automatic detection and addition of i18n imports:

```javascript
import i18n from "@/i18n";
import k from "@/i18n/keys";
```

## Usage

### Finding Russian Texts
```bash
node i18n-replace.js
```

### Bulk Replacement
```bash
node bulk-i18n-replace.js
```

## File Processing

The scripts process the following file types:
- `.js` - JavaScript files
- `.jsx` - React components  
- `.ts` - TypeScript files
- `.tsx` - TypeScript React components

## Directory Structure

Excluded directories:
- `node_modules/`
- `.git/`
- `.next/`
- `dist/`
- `build/`

## Integration

These scripts are designed to work with the SmartSearch i18n system:

- **Keys**: `web/src/i18n/keys.js`
- **Russian**: `web/src/i18n/russian.js` 
- **English**: `web/src/i18n/english.js`

## Development Notes

The internationalized versions include placeholder comments for i18n keys:
- `{{TRANSLATIONS_LIST_COMMENT}}`
- `{{FORMS_AND_VALIDATION_COMMENT}}`
- `{{FIND_RUSSIAN_TEXTS_FUNCTION_COMMENT}}`
- `{{REPLACE_RUSSIAN_TEXTS_FUNCTION_COMMENT}}`

These can be dynamically replaced with actual translations when the scripts are used in a fully internationalized environment.
