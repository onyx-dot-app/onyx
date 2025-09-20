# # leaving this here for future mem debugging efforts
# import os
# from typing import Any

# import psutil
# from pympler import asizeof

# from onyx.utils.logger import setup_logger

# logger = setup_logger()

#
# def log_memory_usage(
#     label: str,
#     specific_object: Any = None,
#     object_label: str = "",
# ) -> None:
#     """Log current process memory usage and optionally the size of a specific object.

#     Args:
#         label: A descriptive label for the current location/operation in code
#         specific_object: Optional object to measure the size of
#         object_label: Optional label describing the specific object
#     """
#     try:
#         # Get current process memory info
#         process = psutil.Process(os.getpid())
#         memory_info = process.memory_info()

#         # Convert to MB for readability
#         rss_mb = memory_info.rss / (1024 * 1024)
#         vms_mb = memory_info.vms / (1024 * 1024)

#         log_parts = [f"MEMORY[{label}]", f"RSS: {rss_mb:.2f}MB", f"VMS: {vms_mb:.2f}MB"]

#         # Add object size if provided
#         if specific_object is not None:
#             try:
#                 # recursively calculate the size of the object
#                 obj_size = asizeof.asizeof(specific_object)
#                 obj_size_mb = obj_size / (1024 * 1024)
#                 obj_desc = f"[{object_label}]" if object_label else "[object]"
#                 log_parts.append(f"OBJ{obj_desc}: {obj_size_mb:.2f}MB")
#             except Exception as e:
#                 log_parts.append(f"OBJ_SIZE_ERROR: {str(e)}")

#         logger.info(" | ".join(log_parts))

#     except Exception as e:
#         logger.warning(f"Failed to log memory usage for {label}: {str(e)}")

# For example, use this like:
# log_memory_usage("my_operation", my_large_object, "my_large_object")
