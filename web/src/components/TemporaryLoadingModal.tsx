export default function TemporaryLoadingModal({
  content,
}: {
  content: string;
}) {
  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-black bg-opacity-30">
      <div className="bg-white rounded-xl p-8 shadow-2xl flex items-center space-x-6">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-neutral-950"></div>
        <p className="text-xl font-medium text-gray-800">{content}</p>
      </div>
    </div>
  );
}
