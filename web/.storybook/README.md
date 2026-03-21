# Storybook de ACTIVA

Storybook es un entorno aislado para desarrollar componentes UI. Renderiza cada componente en una "story" independiente fuera de la app principal, para verificar apariencia, probar props y detectar regresiones sin navegar por toda la aplicacion.

El Storybook de ACTIVA cubre toda la libreria de componentes, desde primitivas de bajo nivel en `@opal/core` hasta `refresh-components`, y sirve como referencia compartida para diseno e ingenieria.

**Produccion:** actualiza esta linea con la URL publica final del Storybook de ACTIVA cuando exista.

## Ejecutarlo localmente

```bash
cd web
npm run storybook
npm run storybook:build
```

- `npm run storybook` levanta el servidor en `http://localhost:6006`
- `npm run storybook:build` genera la salida estatica en `storybook-static/`

## Escribir stories

Las stories viven junto al codigo fuente del componente:

```text
lib/opal/src/core/interactive/
|-- components.tsx
|-- Interactive.stories.tsx
`-- styles.css

src/refresh-components/buttons/
|-- Button.tsx
`-- Button.stories.tsx
```

### Plantilla minima

```tsx
import type { Meta, StoryObj } from "@storybook/react";
import { MyComponent } from "./MyComponent";

const meta: Meta<typeof MyComponent> = {
  title: "Category/MyComponent",
  component: MyComponent,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof MyComponent>;

export const Default: Story = {
  args: { label: "Hello" },
};
```

### Convenciones

- **Formato del titulo:** `Core/Name`, `Components/Name`, `Layouts/Name` o `refresh-components/category/Name`
- **Tags:** usa `tags: ["autodocs"]` para generar docs automaticas desde props
- **Decorators:** los componentes que usan tooltips de Radix suelen necesitar `TooltipPrimitive.Provider`
- **Layout:** usa `parameters: { layout: "fullscreen" }` para modales o popovers que usan portales

## Dark mode

Usa el selector de tema en la toolbar de Storybook para alternar entre light y dark mode. Esto agrega o quita la clase `dark` en el preview y deja que los tokens de `colors.css` se adapten automaticamente.

## Deploy

El Storybook de produccion se publica como sitio estatico. El build corre `npm run storybook:build`, genera `storybook-static/` y tu proveedor de hosting debe servir ese directorio.

Los deploys se disparan cuando hay merges a `main` con cambios en:

- `web/lib/opal/`
- `web/src/refresh-components/`
- `web/.storybook/`

## Capas de componentes

| Capa | Ruta | Ejemplos |
|------|------|----------|
| **Core** | `lib/opal/src/core/` | Interactive, Hoverable |
| **Components** | `lib/opal/src/components/` | Button, OpenButton, Tag |
| **Layouts** | `lib/opal/src/layouts/` | Content, ContentAction, IllustrationContent |
| **refresh-components** | `src/refresh-components/` | Inputs, tablas, modales, textos, cards, tiles, etc. |
