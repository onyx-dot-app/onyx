"""Constants for document editor tests."""

SAMPLE_DOCUMENT = """
<html>
<body>
<h1>Sample Document</h1>
<p>This is a sample document.</p>
</body>
</html>
"""

SAMPLE_INSTRUCTIONS = """
1. Change the title to "Modified Article"
"""

EXPECTED_EDITED_DOCUMENT = """
<html>
<body>
<h1>Modified Article</h1>
<p>This is a sample document.</p>
<p>This is a new paragraph.</p>
</body>
</html>
"""

LARGE_DOCUMENT = """
<html>
<body>
    <h1>Product Specifications</h1>
    <section>
        <h2>Materials</h2>
        <p>The product is made from high-quality plastic components that ensure durability and longevity.</p>
        <p>All parts are certified for safety and environmental compliance.</p>
        <ul>
            <li>Main body:</li>
            <li>Connectors:</li>
            <li>Mounting brackets:</li>
        </ul>
    </section>
    <section>
        <h2>Features</h2>
        <p>The construction allows for easy maintenance and cleaning.</p>
        <p>All surfaces are treated with a special coating for enhanced durability.</p>
    </section>
</body>
</html>
"""

TABLE_DOCUMENT = """
<table>
   <tbody>
      <tr>
         <th>OXOS MEDICAL, INC</th>
      </tr>
      <tr></tr>
      <tr>
         <td>Document:</td>
         <td>DR-M02-005 - Design Inputs & Specifications</td>
      </tr>
      <tr>
         <td>Project:</td>
         <td>M02</td>
      </tr>
      <tr></tr>
      <tr>
         <td>APPROVALS / DOCUMENT REVISION HISTORY</td>
      </tr>
      <tr>
         <td>Revision</td>
         <td>Description</td>
         <td>DCO #</td>
         <td>Approved By</td>
         <td>Eff. Date</td>
         <td>Digital Key</td>
      </tr>
      <tr>
         <td>A</td>
         <td>Initial Release</td>
         <td>24-190</td>
         <td>Engineering\nQuality Engineering\nRegulatory Affairs</td>
         <td>2024-04-26</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1LkDlGzPf-1DObbj63nwFrkWbi6wIoDExHGdPs0icyRE/edit#gid=2040511898\">https://docs.google.com/spreadsheets/d/1LkDlGzPf-1DObbj63nwFrkWbi6wIoDExHGdPs0icyRE/edit#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>B</td>
         <td>Updated Product Update, Indications for Use, & Contraindications\nSummative Usability Results Update; Requirement updates per Phase 3 testing.\nAdjusted SSD lockout and added angle req for SID and SSD.\nRemoved req for inversion in any mode</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1u_JQf_wD7pDjHQS2ntIvEQWOEVKBJnmq6tHzW4f6GdY/edit?pli=1#gid=1257609937\">Refer to ECR-444</a></td>
         <td></td>
         <td></td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/11Xw3zlfEq8Tkv8Ljfu778_E5Liu_NrUkLe7HfRG8v_8/edit#gid=2040511898\">https://docs.google.com/spreadsheets/d/11Xw3zlfEq8Tkv8Ljfu778_E5Liu_NrUkLe7HfRG8v_8/edit#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>C</td>
         <td>Updated Contraindications</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1sFxB1wpb4ykJ_8WNSKu9BgFIVHjz6mAabfRSg4th6b8/edit#gid=1257609937\">Refer to ECR-461</a></td>
         <td></td>
         <td></td>
         <td><a href=\"#gid=2040511898\">https://docs.google.com/spreadsheets/d/1-qTcJklVBWCc9t5T4OtB8x3ptC4Vh9-Cj1v3MW_alUE/edit#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>D</td>
         <td>Updates per 3.2.0 MC2 App UI changes and summative usability</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/12BOXhPBojJxSpM_xPGiTLmg2VhSf2qbpw4lclHmV45I/edit?gid=1257609937#gid=1257609937\">Refer to ECR-570</a></td>
         <td></td>
         <td></td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1yGp1euzkWaZXDvMAun6g-1r_V7uYgsm3aDcB7t4W3-0/edit?gid=2040511898#gid=2040511898\">https://docs.google.com/spreadsheets/d/1yGp1euzkWaZXDvMAun6g-1r_V7uYgsm3aDcB7t4W3-0/edit?gid=2040511898#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>E</td>
         <td>Removal of RSK_R365 and several IFU requirements per RSK-M02-010 Rev D, Update PRD to reflect Indications for Use</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1RQE5Kq87iYKLarJlNR0iSESrLBWqsuCRKh5RapUXmdw/edit?gid=1257609937#gid=1257609937\">Refer to ECR-601</a></td>
         <td></td>
         <td></td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/12JRdkS3t34rr490ryVAQxOXhS2cym8eX6l3QqS6hPb4/edit?gid=2040511898#gid=2040511898\">https://docs.google.com/spreadsheets/d/12JRdkS3t34rr490ryVAQxOXhS2cym8eX6l3QqS6hPb4/edit?gid=2040511898#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>F</td>
         <td>Update to PRD 3.11 to include prevention of handheld serial radiography</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1iL8AmdsNwGzb5T779wPFFN9wvTcGfIsU5QmzZnlnBkM/edit?gid=1257609937#gid=1257609937\">Refer to ECR-643</a></td>
         <td></td>
         <td></td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1sSxRmhSm5SmeieMfNAL1_xPmujeobQRKTCaY57QEEtY/edit?gid=2040511898#gid=2040511898\">https://docs.google.com/spreadsheets/d/1sSxRmhSm5SmeieMfNAL1_xPmujeobQRKTCaY57QEEtY/edit?gid=2040511898#gid=2040511898</a></td>
      </tr>
      <tr>
         <td>G</td>
         <td>-Added RSK_R384 through RSK_R392\n-Corrected information in RSK_R329 specification as previous information was inaccurate\n-Removed RSK_R279. Item is a component supplier requirement\n-Removed RSK_R267. Dose verification was performed as part of software V&V\n-Corrected PN listed in PRD7.9 Specification</td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1Oe8snU2Wo3R100FoJM6YKzFee_sewQ3iQa61EhMq-18/edit?gid=1257609937#gid=1257609937\">Refer to ECR-741</a></td>
         <td></td>
         <td></td>
         <td><a href=\"https://docs.google.com/spreadsheets/d/1G9BZIANI0wURZxs3LDildOziwN6DxLQfW_kS7g_dyoA/\">https://docs.google.com/spreadsheets/d/1G9BZIANI0wURZxs3LDildOziwN6DxLQfW_kS7g_dyoA/</a></td>
      </tr>
   </tbody>
</table>
"""


WORD_REPLACEMENT_INSTRUCTIONS = (
    "Change all instances of the word 'plastic' to 'metal' in the document."
)


def get_default_llm():
    """Get a default LLM instance for testing.

    Returns:
        DefaultMultiLLM: A configured LLM instance for testing.

    Raises:
        ValueError: If OPENAI_API_KEY is not set in environment variables.
    """
    import os

    from onyx.llm.chat_llm import DefaultMultiLLM

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in environment variables")

    return DefaultMultiLLM(
        model_provider="openai",
        model_name="gpt-4",  # Using GPT-4 for better reliability
        temperature=0.0,
        api_key=api_key,
        max_input_tokens=10000,
    )


def get_test_document_editor(llm):
    """Get a DocumentEditorTool instance for testing.

    Args:
        llm: The LLM instance to use

    Returns:
        DocumentEditorTool: A configured document editor instance for testing
    """
    from onyx.tools.tool_implementations.document.document_editor_tool import (
        DocumentEditorTool,
    )

    return DocumentEditorTool(llm=llm, documents={"sample": SAMPLE_DOCUMENT})
