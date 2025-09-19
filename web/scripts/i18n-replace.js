#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

// Функция для поиска русских текстов в файле
function findRussianTexts(filePath) {
  try {
    const content = fs.readFileSync(filePath, "utf8");
    const russianRegex = /[а-яё]+/gi;
    const matches = content.match(russianRegex);
    return matches ? [...new Set(matches)] : [];
  } catch (error) {
    console.error(`Error reading file ${filePath}:`, error.message);
    return [];
  }
}

// Функция для замены русских текстов на i18n ключи
function replaceRussianTexts(filePath, replacements) {
  try {
    let content = fs.readFileSync(filePath, "utf8");

    // Проверяем, есть ли уже импорт i18n
    if (
      !content.includes("import i18n from") &&
      !content.includes("import k from")
    ) {
      // Находим место для добавления импорта
      const importMatch = content.match(/import.*from.*["'].*["'];/);
      if (importMatch) {
        const importIndex =
          content.lastIndexOf(importMatch[0]) + importMatch[0].length;
        content =
          content.slice(0, importIndex) +
          '\nimport i18n from "@/i18n/init";\nimport k from "../../../i18n/keys";' +
          content.slice(importIndex);
      }
    }

    // Заменяем русские тексты
    for (const [russianText, key] of Object.entries(replacements)) {
      const regex = new RegExp(`"${russianText}"`, "g");
      content = content.replace(regex, `i18n.t(k.${key})`);
    }

    fs.writeFileSync(filePath, content, "utf8");
    console.log(`Updated ${filePath}`);
  } catch (error) {
    console.error(`Error updating file ${filePath}:`, error.message);
  }
}

// Основная функция
function main() {
  const srcDir = path.join(__dirname, "../src");
  const files = [];

  // Рекурсивно находим все .tsx и .ts файлы
  function findFiles(dir) {
    const items = fs.readdirSync(dir);
    for (const item of items) {
      const fullPath = path.join(dir, item);
      const stat = fs.statSync(fullPath);

      if (
        stat.isDirectory() &&
        !item.startsWith(".") &&
        item !== "node_modules"
      ) {
        findFiles(fullPath);
      } else if (
        stat.isFile() &&
        (item.endsWith(".tsx") || item.endsWith(".ts"))
      ) {
        files.push(fullPath);
      }
    }
  }

  findFiles(srcDir);

  console.log(`Found ${files.length} files to process`);

  // Обрабатываем каждый файл
  for (const file of files) {
    const russianTexts = findRussianTexts(file);
    if (russianTexts.length > 0) {
      console.log(`\nFile: ${file}`);
      console.log(`Russian texts found: ${russianTexts.join(", ")}`);

      // Здесь можно добавить логику для автоматической замены
      // или создать маппинг русских текстов на ключи
    }
  }
}

if (require.main === module) {
  main();
}

module.exports = { findRussianTexts, replaceRussianTexts };
