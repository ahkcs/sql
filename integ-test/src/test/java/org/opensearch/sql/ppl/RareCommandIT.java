/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 */

package org.opensearch.sql.ppl;

import static org.opensearch.sql.legacy.TestsConstants.TEST_INDEX_ACCOUNT;
import static org.opensearch.sql.util.MatcherUtils.rows;
import static org.opensearch.sql.util.MatcherUtils.verifyDataRows;

import java.io.IOException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.jupiter.api.Test;

public class RareCommandIT extends PPLIntegTestCase {

  @Override
  public void init() throws Exception {
    super.init();
    loadIndex(Index.ACCOUNT);
    setQuerySizeLimit(2000);
  }

  @After
  public void afterTest() throws IOException {
    resetQuerySizeLimit();
  }

  @Test
  public void testRareWithoutGroup() throws IOException {
    JSONObject result = executeQuery(String.format("source=%s | rare gender", TEST_INDEX_ACCOUNT));
    verifyDataRows(result, rows("F"), rows("M"));
  }

  @Test
  public void testRareWithGroup() throws IOException {
    JSONObject result =
        executeQuery(String.format("source=%s | rare state by gender", TEST_INDEX_ACCOUNT));
    verifyDataRows(
        result,
        rows("F", "DE"),
        rows("F", "WI"),
        rows("F", "OR"),
        rows("F", "CT"),
        rows("F", "WA"),
        rows("F", "SC"),
        rows("F", "OK"),
        rows("F", "KS"),
        rows("F", "CO"),
        rows("F", "VA"),
        rows("M", "NE"),
        rows("M", "RI"),
        rows("M", "NV"),
        rows("M", "MI"),
        rows("M", "MT"),
        rows("M", "AZ"),
        rows("M", "NM"),
        rows("M", "SD"),
        rows("M", "KY"),
        rows("M", "IN"));
  }
}
