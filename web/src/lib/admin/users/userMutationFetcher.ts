const userMutationFetcher = async (
  url: string,
  { arg }: { arg: { user_email: string } }
) => {
  return fetch(url, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_email: arg.user_email,
    }),
  }).then(async (res) => {
    if (res.ok) return res.json();
    const errorDetail = (await res.json()).detail;
    throw Error(errorDetail);
  });
};

export default userMutationFetcher;
