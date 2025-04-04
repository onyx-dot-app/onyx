
/**
 * Retrieves the given Google doc by id and extracts dates, people, and rich links
 * from it into a JSON keyed by tab, paragraph, and non-text-component index.
 * 
 */
function docToChips(document_id) {
  const doc = DocumentApp.openById(document_id);
  const tabs = doc.getTabs();
  const ret = new Map();
  tabs.map((tab, tabInd) => {
    const docTab = tab.asDocumentTab();
    const body = docTab.getBody();
    for (let tabChildInd = 0; tabChildInd < body.getNumChildren(); tabChildInd++) {
      var tabChild = body.getChild(tabChildInd);
      var callback = ((nonTextInd, replaceText) => {ret[getKey(tabInd, tabChildInd, nonTextInd)] = replaceText;});
      switch (tabChild.getType()) {
        case DocumentApp.ElementType.PARAGRAPH:
          parseParagraph(tabChild.asParagraph(), callback);
          console.log("paragraph", tabChild.asParagraph().getText());
          break;
        case DocumentApp.ElementType.TABLE:
          console.log("table");
          parseTable(tabChild.asTable(), callback);
          break;
        case DocumentApp.ElementType.LIST_ITEM:
          var listItem = tabChild.asListItem();
          //console.log("list item:", listItem.getText(), listItem.getNumChildren());
          //console.log(listItem.getChild(0).asText().getText());
          parseParagraph(tabChild.asListItem(), callback);
          break;
        default:
          console.log("found unknown tab body child of type: ", tabChild.getType().toString());
      }
    }
  });
  console.log(ret);
  return ret;
}

// uncomment and paste in a file id (and change the main function to "test")
// to test the docToChips function
// function test() {
//   return docToChips("document id goes here");
// }

function getKey(tabInd, paragraphInd, nonTextInd) {
  return tabInd + "_" + paragraphInd + "_" + nonTextInd;
}

// also used for list items
function parseParagraph(paragraph, callback) {
  var nonTextInd = 0;
  for (let i = 0; i < paragraph.getNumChildren(); i++) { //
    var child = paragraph.getChild(i);
    switch (child.getType()) {
      case DocumentApp.ElementType.DATE:
        console.log(child.asDate().getDisplayText());
        callback(nonTextInd, child.asDate().getDisplayText());
        break;
      case DocumentApp.ElementType.EQUATION:
        var eqStr = child.getText();
        console.log("equation: ", eqStr);
        callback(nonTextInd, eqStr);
        break;
      case DocumentApp.ElementType.PERSON:
        var personStr = "<name: " + child.asPerson().getName() + ", email: "+ child.asPerson().getEmail() + ">";
        console.log(personStr);
        //callback(nonTextInd, personStr);
        nonTextInd--; // Advanced Docs API picks up people
        break;
      case DocumentApp.ElementType.RICH_LINK:
        var richLink = child.asRichLink()
        var linkStr = "<title: " + richLink.getTitle() + ", type:" + richLink.getMimeType() + ">"
        console.log(linkStr);
        // callback(nonTextInd, child.asRichLink().getUrl());
        nonTextInd--; // Advanced Docs API picks up rich links
        break;
      case DocumentApp.ElementType.TEXT:
        console.log("text: "+ child.asText().getText());
        //console.log(child.asText().)
        nonTextInd--;
        break;
      case DocumentApp.ElementType.UNSUPPORTED:
        console.log("unsupported element type");
        break;
      default:
        console.log("found special element type:", child.getType().toString());
    }
    nonTextInd++;
  }
}

function parseTable(table, callback) {
  var lastSeenInCell = 0;
  var allSeenElems = 0
  const tableCallback = ((nonTextInd, replaceText) => {
    callback(allSeenElems + lastSeenInCell + nonTextInd, replaceText);
    lastSeenInCell++;
  });
  for (let rowInd = 0; rowInd < table.getNumChildren(); rowInd++) {
    var row = table.getChild(rowInd);
    if (row.getType() !== DocumentApp.ElementType.TABLE_ROW) {
      console.log("table child type: ", row.getType().toString());
      continue;
    }

    for (let colInd = 0; colInd < row.getNumChildren(); colInd++) {
      var cell = row.getChild(colInd);
      if (cell.getType() !== DocumentApp.ElementType.TABLE_CELL) {
        console.log("row child type: ", cell.getType().toString());
        continue;
      }

      for (let itemInd = 0; itemInd < cell.getNumChildren(); itemInd++) {
        var item = cell.getChild(itemInd);
        console.log(item.getType().toString());
        switch (item.getType()) {
          case DocumentApp.ElementType.PARAGRAPH:
          case DocumentApp.ElementType.LIST_ITEM:
            parseParagraph(item, tableCallback);
            break;
          case DocumentApp.ElementType.TABLE:
            parseTable(item, tableCallback);
            break;
        }
      }
      allSeenElems += lastSeenInCell;
      lastSeenInCell = 0;
    }
  }
}