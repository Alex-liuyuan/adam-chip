#include <string.h>
#include "rt_ai.h"

static int hash_equal(const uint8_t left[32], const uint8_t right[32])
{
    return memcmp(left, right, 32U) == 0;
}

int rt_ai_evaluate_deployment(const rt_ai_aeg_t *aeg, const rt_ai_trust_bundle_t *trust, rt_ai_evaluation_result_t *result)
{
    uint16_t index;
    if (result == NULL) return RT_AI_ERR_INVALID;
    memset(result, 0, sizeof(*result));
    result->status = RT_AI_ERR_EVIDENCE;
    if (aeg == NULL || trust == NULL || !aeg->deployable || aeg->legacy ||
        trust->obligation_count == 0U || trust->obligation_count > RT_AI_MAX_EVIDENCE ||
        trust->allowed_verifier_count == 0U || trust->allowed_verifier_count > RT_AI_MAX_EVIDENCE) {
        result->reason = 1U; return result->status;
    }
    if (!hash_equal(aeg->plan_sha256, trust->plan_sha256) || !hash_equal(aeg->evidence_sha256, trust->evidence_sha256) ||
        !hash_equal(aeg->policy_sha256, trust->policy_sha256) || !hash_equal(aeg->model_sha256, trust->model_sha256) ||
        !hash_equal(aeg->target_sha256, trust->target_sha256) || !hash_equal(aeg->runtime_abi_sha256, trust->runtime_abi_sha256) ||
        !hash_equal(aeg->provider_abi_sha256, trust->provider_abi_sha256)) {
        result->reason = 2U; return result->status;
    }
    if (aeg->evidence_count != trust->obligation_count) { result->reason = 3U; return result->status; }
    for (index = 0U; index < aeg->evidence_count; ++index) {
        uint16_t allowed;
        int verifier_allowed = 0;
        result->obligation_index = index;
        if (aeg->evidence_status[index] != 1U ||
            !hash_equal(aeg->obligation_sha256[index], trust->obligation_sha256[index]) ||
            !hash_equal(aeg->scope_sha256[index], trust->scope_sha256[index]) ||
            !hash_equal(aeg->artifact_sha256[index], trust->artifact_sha256[index]) ||
            !hash_equal(aeg->verifier_sha256[index], trust->verifier_sha256[index]) ||
            aeg->evidence_resource[index] != trust->evidence_resource[index]) {
            result->reason = 3U; return result->status;
        }
        for (allowed = 0U; allowed < trust->allowed_verifier_count; ++allowed)
            if (hash_equal(aeg->verifier_sha256[index], trust->allowed_verifier_sha256[allowed])) verifier_allowed = 1;
        if (!verifier_allowed) { result->reason = 4U; return result->status; }
    }
    for (index = 0U; index < aeg->header.segment_count; ++index) {
        if (aeg->evidence_index[index] >= aeg->evidence_count || aeg->evidence_resource[aeg->evidence_index[index]] != aeg->segments[index].resource) {
            result->obligation_index = aeg->evidence_index[index]; result->reason = 5U; return result->status;
        }
    }
    for (index = 0U; index < aeg->fallback_segment_count; ++index)
        if (aeg->fallback_evidence[index] >= aeg->evidence_count || aeg->evidence_resource[aeg->fallback_evidence[index]] != aeg->fallback_storage[index].resource) {
            result->obligation_index = aeg->fallback_evidence[index]; result->reason = 6U; return result->status;
        }
    if (aeg->fallback_segment_count == 0U ||
        aeg->minimum_interarrival_us == 0U || aeg->relative_deadline_us == 0U || aeg->cancel_ack_timeout_us == 0U || aeg->reset_timeout_us == 0U || aeg->reinit_timeout_us == 0U) {
        result->reason = 7U; return result->status;
    }
    result->status = RT_AI_OK;
    result->reason = 0U;
    return RT_AI_OK;
}
