export function Tag({ tone }: { tone: string }) {
  return <span className={cn("tag-root", "tag-tone-" + tone)} />;
}
