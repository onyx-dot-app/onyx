pipeline {
  environment {
    RANCHER_STACKID = ""
    RANCHER_ENVID = ""
    GIT_NAME = "danswer"
    registry = "eeacms/danswer"
    template = ""
    dockerImage = ''
    tagName = ''
  }

  agent any

  stages {

    stage('Build & Push ( on tag )') {
      when {
        anyOf {
          buildingTag()
        }
      }
      steps {
        parallel(

          "WEB": {
            node(label: 'docker-big-jobs') {
            script {
              checkout scm
              if (env.BRANCH_NAME == 'eea') {
                tagName = 'web'
              } else {
                tagName = "web-$BRANCH_NAME"
              }
              try {
                cd web
                dockerImage = docker.build("$registry:$tagName", "--no-cache web")
                docker.withRegistry( '', 'eeajenkins' ) {
                dockerImage.push()
                  }
              } finally {
                sh "docker rmi $registry:$tagName"
              }
            }
          }
          },

          "BACKEND": {
            node(label: 'docker-big-jobs') {
            script {
              checkout scm
              if (env.BRANCH_NAME == 'eea') {
                tagName = 'backend'
              } else {
                tagName = "backend-$BRANCH_NAME"
              }
              try {
                cd backend
                dockerImage = docker.build("$registry:$tagName", "--no-cache web")
                docker.withRegistry( '', 'eeajenkins' ) {
                dockerImage.push()
                  }
              } finally {
                sh "docker rmi $registry:$tagName"
              }
            }
          }
          },
          
          "MODEL_SERVER": {
            node(label: 'docker-big-jobs') {
            script {
              checkout scm
              if (env.BRANCH_NAME == 'eea') {
                tagName = 'model_server'
              } else {
                tagName = "model_server-$BRANCH_NAME"
              }
              try {
                cd web
                dockerImage = docker.build("$registry:$tagName", "-f Dockerfile.model_server --no-cache web")
                docker.withRegistry( '', 'eeajenkins' ) {
                dockerImage.push()
                  }
              } finally {
                sh "docker rmi $registry:$tagName"
              }
            }
          }
          },
        )
      }
    }


    stage('Release catalog ( on tag )') {
      when {
        buildingTag()
      }
      steps{
        node(label: 'docker') {
          withCredentials([string(credentialsId: 'eea-jenkins-token', variable: 'GITHUB_TOKEN'),  usernamePassword(credentialsId: 'jekinsdockerhub', usernameVariable: 'DOCKERHUB_USER', passwordVariable: 'DOCKERHUB_PASS')]) {
            sh '''docker pull eeacms/gitflow; docker run -i --rm --name="$BUILD_TAG-release"  -e GIT_BRANCH="$BRANCH_NAME" -e GIT_NAME="$GIT_NAME" -e DOCKERHUB_REPO="$registry" -e GIT_TOKEN="$GITHUB_TOKEN" -e DOCKERHUB_USER="$DOCKERHUB_USER" -e DOCKERHUB_PASS="$DOCKERHUB_PASS"  -e DEPENDENT_DOCKERFILE_URL="$DEPENDENT_DOCKERFILE_URL" -e RANCHER_CATALOG_PATHS="$template" -e DOCKERHUB_REPO_PREFIX="web\\-\\|backend\\-\\|model_server\\-" -e GITFLOW_BEHAVIOR="RUN_ON_TAG" eeacms/gitflow'''
         }
        }
      }
    }


  }

  post {
    changed {
      script {
        def url = "${env.BUILD_URL}/display/redirect"
        def status = currentBuild.currentResult
        def subject = "${status}: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'"
        def details = """<h1>${env.JOB_NAME} - Build #${env.BUILD_NUMBER} - ${status}</h1>
                         <p>Check console output at <a href="${url}">${env.JOB_BASE_NAME} - #${env.BUILD_NUMBER}</a></p>
                      """
        emailext (subject: '$DEFAULT_SUBJECT', to: '$DEFAULT_RECIPIENTS', body: details)
      }
    }
  }
}
