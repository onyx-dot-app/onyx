/* Animations (formerly Hoverable) */
export {
  Hoverable,
  type HoverableRootProps,
  type HoverableItemProps,
  type HoverableItemVariant,
} from "@opal/core/animations/components";

/* Interactive — compound component */
import { InteractiveStateless } from "@opal/core/interactive/stateless/components";
import { InteractiveStateful } from "@opal/core/interactive/stateful/components";
import { InteractiveContainer } from "@opal/core/interactive/container/components";
import { Foldable } from "@opal/core/interactive/foldable/components";

const Interactive = {
  Stateless: InteractiveStateless,
  Stateful: InteractiveStateful,
  Container: InteractiveContainer,
  Foldable,
};

export { Interactive };

/* Interactive — types */
export type {
  InteractiveStatelessProps,
  InteractiveStatelessVariant,
  InteractiveStatelessProminence,
  InteractiveStatelessInteraction,
} from "@opal/core/interactive/stateless/components";

export type {
  InteractiveStatefulProps,
  InteractiveStatefulVariant,
  InteractiveStatefulState,
  InteractiveStatefulInteraction,
} from "@opal/core/interactive/stateful/components";

export type {
  InteractiveContainerProps,
  InteractiveContainerRoundingVariant,
} from "@opal/core/interactive/container/components";

export type { FoldableProps } from "@opal/core/interactive/foldable/components";
