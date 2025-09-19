const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

// Путь к исходной папке
const srcPath = path.join(__dirname, "../src");

// Получаем все файлы с использованием i18n.t(
function getAllFilesWithI18n() {
  try {
    const result = execSync(
      'npx rg -l "i18n\\.t\\(" --type ts --type tsx --type js --type jsx',
      {
        cwd: srcPath,
        encoding: "utf8",
      }
    );
    return result.trim().split("\n").filter(Boolean);
  } catch (error) {
    console.log("No files found with ripgrep, falling back to manual search");
    return [];
  }
}

// Обновляет файл для использования useTranslation хука
function updateFile(filePath) {
  const fullPath = path.join(srcPath, filePath);

  if (!fs.existsSync(fullPath)) {
    console.log(`File not found: ${fullPath}`);
    return false;
  }

  let content = fs.readFileSync(fullPath, "utf8");
  const originalContent = content;

  // Пропускаем файлы, которые не нужно обновлять
  if (filePath.includes("/i18n/") || filePath.includes("layout.tsx")) {
    console.log(`Skipping: ${filePath}`);
    return false;
  }

  // Проверяем, есть ли использование i18n.t(
  if (!content.includes("i18n.t(")) {
    return false;
  }

  console.log(`Updating: ${filePath}`);

  // 1. Заменяем импорт i18n
  content = content.replace(/import i18n from ["']@\/i18n\/init["'];?\n/g, "");

  // 2. Добавляем импорт useTranslation, если его нет
  if (!content.includes("useTranslation")) {
    // Ищем существующие импорты из @/ или относительные
    const importMatch = content.match(/import.*from ["'][@.].*["'];?\n/);
    if (importMatch) {
      const insertIndex =
        content.indexOf(importMatch[0]) + importMatch[0].length;
      content =
        content.slice(0, insertIndex) +
        'import { useTranslation } from "@/hooks/useTranslation";\n' +
        content.slice(insertIndex);
    } else {
      // Добавляем в начало после "use client" если есть
      const useClientMatch = content.match(/"use client";\s*\n/);
      if (useClientMatch) {
        const insertIndex =
          content.indexOf(useClientMatch[0]) + useClientMatch[0].length;
        content =
          content.slice(0, insertIndex) +
          'import { useTranslation } from "@/hooks/useTranslation";\n' +
          content.slice(insertIndex);
      } else {
        content =
          'import { useTranslation } from "@/hooks/useTranslation";\n' +
          content;
      }
    }
  }

  // 3. Находим основные функции компонентов и добавляем хук
  const functionMatches = content.matchAll(
    /(?:export\s+)?(?:default\s+)?function\s+(\w+)\s*\([^{]*\)\s*\{/g
  );
  let addedHooks = new Set();

  for (const match of functionMatches) {
    const functionName = match[1];
    const functionStart = match.index;
    const openBraceIndex = content.indexOf("{", functionStart);

    // Ищем следующую строку после открывающей скобки
    let insertPoint = openBraceIndex + 1;
    while (insertPoint < content.length && /\s/.test(content[insertPoint])) {
      insertPoint++;
    }

    // Проверяем, нет ли уже хука в этой функции
    const functionEnd = findFunctionEnd(content, openBraceIndex);
    const functionBody = content.slice(openBraceIndex, functionEnd);

    if (
      functionBody.includes("i18n.t(") &&
      !functionBody.includes("const { t } = useTranslation()") &&
      !addedHooks.has(functionName)
    ) {
      content =
        content.slice(0, insertPoint) +
        "\n  const { t } = useTranslation();" +
        content.slice(insertPoint);
      addedHooks.add(functionName);
    }
  }

  // 4. Заменяем все i18n.t( на t(
  content = content.replace(/i18n\.t\(/g, "t(");

  // Сохраняем файл только если изменения есть
  if (content !== originalContent) {
    fs.writeFileSync(fullPath, content);
    console.log(`✓ Updated: ${filePath}`);
    return true;
  }

  return false;
}

// Находит конец функции (упрощенная версия)
function findFunctionEnd(content, startIndex) {
  let braceCount = 1;
  let index = startIndex + 1;

  while (index < content.length && braceCount > 0) {
    if (content[index] === "{") {
      braceCount++;
    } else if (content[index] === "}") {
      braceCount--;
    }
    index++;
  }

  return index;
}

// Основная функция
function main() {
  console.log("🔍 Searching for files with i18n.t() usage...");

  // Получаем список файлов
  const files = getAllFilesWithI18n();

  if (files.length === 0) {
    console.log("No files found with i18n.t() usage");
    return;
  }

  console.log(`Found ${files.length} files to update`);

  let updatedCount = 0;

  files.forEach((file) => {
    if (updateFile(file)) {
      updatedCount++;
    }
  });

  console.log(`\n✅ Updated ${updatedCount} files`);
  console.log("\n⚠️  Please review the changes and test the application");
}

if (require.main === module) {
  main();
}

module.exports = { updateFile, getAllFilesWithI18n };





