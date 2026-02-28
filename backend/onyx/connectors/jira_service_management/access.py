from typing import Any
from jira import JIRA

def get_project_permissions(
    jira_client: JIRA, 
    jira_project: str, 
    add_prefix: bool = False
) -> list[str]:
    """
    Obtiene los grupos o usuarios que tienen acceso al proyecto de Service Management.
    """
    try:
        # Intentamos obtener los roles del proyecto
        roles = jira_client.project_roles(jira_project)
        allowed_entities = []
        
        for role_name, role_info in roles.items():
            # Usualmente los roles 'Service Desk Customers' y 'Agents' son los importantes
            role_details = jira_client.project_role(jira_project, role_info['id'])
            for actor in role_details.actors:
                name = actor.name
                if add_prefix:
                    name = f"jira_sm:{name}"
                allowed_entities.append(name)
        
        return list(set(allowed_entities))
    except Exception:
        # Si falla, devolvemos una lista vacía para que solo los admins vean el contenido (modo seguro)
        return []