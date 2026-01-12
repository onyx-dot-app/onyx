# Opensearch Idiosyncrasies

## How it works at a high level
Opensearch has 2 phases, a `Search` phase and a `Fetch` phase. The `Search` phase works by getting the document scores on each
shard separately, then typically a fetch phase grabs all of the relevant fields/data for returning to the user. There is also
an intermediate phase (seemingly built specifically to handle hybrid search queries) which can run in between as a processor.
References:
https://docs.opensearch.org/latest/search-plugins/search-pipelines/search-processors/
https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
https://docs.opensearch.org/latest/query-dsl/compound/hybrid/

## How Hybrid queries work
Hybrid queries are basically parallel queries that each run through their own `Search` phase and do not interact in any way.
They also run across all the shards. It is not entirely clear what happens if a combination pipeline is not specified for them,
perhaps the scores are just summed.

When the normalization processor is applied to keyword/vector hybrid searches, documents that show up due to keyword match may
not also have showed up in the vector search and vice versa. In these situations, it just receives a 0 score for the missing
query component. Opensearch does not run another phase to recapture those missing values. The impact of this is that after
normalizing, the missing scores are 0 but this is a higher score than if it actually received a non-zero score.

This may not be immediately obvious so an explanation is included here. If it got a non-zero score instead, it must be lower
than all of the other scores of the list (otherwise it would have shown up). Therefore it would impact the normalization and
push the other scores higher so that it's not only the lowest score still, but now it's a differentiated lowest score. This is
not strictly the case in a multi-node setup but the high level concept approximately holds. So basically the 0 score is a form
of "minimum value clipping".

## On time decay and boosting
Embedding models do not have a uniform distribution from 0 to 1. The values typically cluster strongly around 0.6 to 0.8 but also
varies between models and even the query. It is not a safe assumption to pre-normalize the scores so we also cannot apply any
additive or multiplicative boost to it. Ie. if results of a doc cluster around 0.6 to 0.8 and I give a 50% penalty to the score,
it doesn't bring a result from the top of the range to 50 percentile, it brings its under the 0.6 and is now the worst match.
Same logic applies to additive boosting.

So these boosts can only be applied after normalization. Unfortunately with Opensearch, the normalization processor runs last
and only applies to the results of the completely independent `Search` phase queries. So if a time based boost (a separate
query which filters on recently updated documents) is added, it would not be able to introduce any new documents
to the set (since the new documents would have no keyword/vector score or already be present) since the 0 scores on keyword
and vector would make the docs which only came because of time filter very low scoring. This can however make some of the lower
scored documents from the union of all the `Search` phase documents to show up higher and potentially not get dropped before
being fetched and returned to the user. But there are other issues of including these:
- There is no way to sort by this field, only a filter, so there's no way to guarantee the best docs even irrespective of the
contents. If there are lots of updates, this may miss
- There is not a good way to normalize this field, the best is to clip it on the bottom.
- This would require using min-max norm but z-score norm is better for the other functions due to things like it being less
sensitive to outliers, better handles distribution drifts (min-max assumes stable meaningful ranges), better for comparing
"unusual-ness" across distributions.

So while it is possible to apply time based boosting at the normalization stage (or specifically to the keyword score), we have
decided it is better to not apply it during the OpenSearch query.

Because of these limitations, Onyx in code applies further refinements, boostings, etc. based on OpenSearch providing an initial
filtering. The impact of time decay and boost should not be so big that we would need orders of magnitude more results back
from OpenSearch.

## Other concepts to be aware of
Within the `Search` phase, there are optional steps like Rescore but these are not useful for the combination/normalization
work that is relevant for the hybrid search. Since the Rescore happens prior to normalization, it's not able to provide any
meaningful operations to the query for our usage.

Because the Title is included in the Contents for both embedding and keyword searches, the Title scores are very low relative to
the actual full contents scoring. It is seen as a boost rather than a core scoring component. Time decay works similarly.
