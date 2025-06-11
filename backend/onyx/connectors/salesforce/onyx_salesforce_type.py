# from typing import Any

# from simple_salesforce import Salesforce
# from simple_salesforce import SFType


# class OnyxSalesforceType:
#     def __init__(self, name: str):
#         self.name = name

#     def describe(self, sf_client: Salesforce) -> Any:
#         sf_object = SFType(
#             self.name, sf_client.session_id, sf_client.sf_instance
#         )
#         result = sf_object.describe()
#         return result

#     def get_queryable_fields(self, sf_client: Salesforce) -> list[str]:
#         object_description = sf_client.describe()
#         if object_description is None:
#             return []

#         fields: list[dict[str, Any]] = object_description["fields"]
#         valid_fields: set[str] = set()
#         field_names_to_remove: set[str] = set()
#         for field in fields:
#             if compound_field_name := field.get("compoundFieldName"):
#                 # We do want to get name fields even if they are compound
#                 if not field.get("nameField"):
#                     field_names_to_remove.add(compound_field_name)

#             field_name = field.get("name")
#             field_type = field.get("type")
#             if field_type in ["base64", "blob", "encryptedstring"]:
#                 # print(f"skipping {sf_type=} {field_name=} {field_type=}")
#                 continue

#             # field_custom = field.get("custom")
#             # if field_custom:
#             #     print(f"custom field: {sf_type=} {field_name=} {field_type=}")

#             if field_name:
#                 valid_fields.add(field_name)

#         return list(valid_fields - field_names_to_remove)
