/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 */

package org.opensearch.sql.sql;

import static org.opensearch.sql.executor.execution.QueryPlanFactory.NO_CONSUMER_RESPONSE_LISTENER;

import lombok.RequiredArgsConstructor;
import org.antlr.v4.runtime.tree.ParseTree;
import org.opensearch.sql.ast.statement.Statement;
import org.opensearch.sql.common.response.ResponseListener;
import org.opensearch.sql.executor.ExecutionEngine.ExplainResponse;
import org.opensearch.sql.executor.ExecutionEngine.QueryResponse;
import org.opensearch.sql.executor.QueryManager;
import org.opensearch.sql.executor.QueryType;
import org.opensearch.sql.executor.execution.AbstractPlan;
import org.opensearch.sql.executor.execution.QueryPlanFactory;
import org.opensearch.sql.sql.antlr.SQLSyntaxParser;
import org.opensearch.sql.sql.domain.SQLQueryRequest;
import org.opensearch.sql.sql.parser.AstBuilder;
import org.opensearch.sql.sql.parser.AstStatementBuilder;

/** SQL service. */
@RequiredArgsConstructor
public class SQLService {

  private final SQLSyntaxParser parser;

  private final QueryManager queryManager;

  private final QueryPlanFactory queryExecutionFactory;

  private final QueryType SQL_QUERY = QueryType.SQL;

  /**
   * Given {@link SQLQueryRequest}, execute it. Using listener to listen result.
   *
   * @param request {@link SQLQueryRequest}
   * @param queryListener callback listener
   * @param explainListener callback listener for explain query
   */
  public void execute(
      SQLQueryRequest request,
      ResponseListener<QueryResponse> queryListener,
      ResponseListener<ExplainResponse> explainListener) {
    try {
      queryManager.submit(plan(request, queryListener, explainListener));
    } catch (Exception e) {
      queryListener.onFailure(e);
    }
  }

  /**
   * Given {@link SQLQueryRequest}, explain it. Using listener to listen result.
   *
   * @param request {@link SQLQueryRequest}
   * @param listener callback listener
   */
  public void explain(SQLQueryRequest request, ResponseListener<ExplainResponse> listener) {
    try {
      queryManager.submit(plan(request, NO_CONSUMER_RESPONSE_LISTENER, listener));
    } catch (Exception e) {
      listener.onFailure(e);
    }
  }

  private AbstractPlan plan(
      SQLQueryRequest request,
      ResponseListener<QueryResponse> queryListener,
      ResponseListener<ExplainResponse> explainListener) {
    boolean isExplainRequest = request.isExplainRequest();
    if (request.getCursor().isPresent()) {
      // Handle v2 cursor here -- legacy cursor was handled earlier.
      if (isExplainRequest) {
        throw new UnsupportedOperationException(
            "Explain of a paged query continuation "
                + "is not supported. Use `explain` for the initial query request.");
      }
      if (request.isCursorCloseRequest()) {
        return queryExecutionFactory.createCloseCursor(
            request.getCursor().get(), SQL_QUERY, queryListener);
      }
      return queryExecutionFactory.create(
          request.getCursor().get(),
          isExplainRequest,
          SQL_QUERY,
          request.getFormat(),
          queryListener,
          explainListener);
    } else {
      // 1.Parse query and convert parse tree (CST) to abstract syntax tree (AST)
      ParseTree cst = parser.parse(request.getQuery());
      Statement statement =
          cst.accept(
              new AstStatementBuilder(
                  new AstBuilder(request.getQuery()),
                  AstStatementBuilder.StatementBuilderContext.builder()
                      .isExplain(isExplainRequest)
                      .fetchSize(request.getFetchSize())
                      .format(request.getFormat())
                      .build()));

      return queryExecutionFactory.create(statement, queryListener, explainListener);
    }
  }
}
